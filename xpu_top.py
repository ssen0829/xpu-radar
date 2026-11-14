import asyncio
import json
import os
import re
import sys
import argparse
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

DEFAULT_NODES = [
    {"alias": "gpu-node-1", "tag": "RTX-4090-1"},
    {"alias": "npu-node-1", "tag": "Ascend-910B"},
]

REMOTE_PROBE_CMD = r"""
if command -v nvidia-smi >/dev/null 2>&1; then
    echo "===TYPE:GPU==="
    nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits
    echo "===APPS==="
    nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits | while IFS=',' read -r uuid pid mem; do
        pid_trim=$(echo $pid | xargs)
        user=$(ps -o user= -p "$pid_trim" 2>/dev/null | xargs)
        echo "$uuid,$pid_trim,${user:-unknown},$mem"
    done
elif command -v npu-smi >/dev/null 2>&1; then
    echo "===TYPE:NPU==="
    npu-smi info
else
    echo "===TYPE:OFFLINE==="
fi
"""

def load_nodes() -> list[dict]:
    base_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    config_path = base_dir / "nodes.json"
    if not config_path.exists():
        config_path.write_text(json.dumps(DEFAULT_NODES, indent=2, ensure_ascii=False), encoding="utf-8")
        return DEFAULT_NODES
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_NODES

async def query_node(node: dict) -> dict:
    alias, tag = node["alias"], node["tag"]
    try:
        creationflags = 0x08000000 if os.name == "nt" else 0
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-o", "ConnectTimeout=4", "-o", "BatchMode=yes", alias, REMOTE_PROBE_CMD,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"alias": alias, "tag": tag, "error": stderr.decode(errors="ignore").strip() or "SSH Failed", "cards": []}
        output = stdout.decode("utf-8", errors="ignore")
        return {"alias": alias, "tag": tag, "error": None, "cards": parse_node_output(alias, tag, output)}
    except Exception as e:
        return {"alias": alias, "tag": tag, "error": str(e), "cards": []}

def parse_node_output(alias: str, tag: str, output: str) -> list[dict]:
    cards = []
    if "===TYPE:GPU===" in output:
        parts = output.split("===APPS===")
        gpu_lines = parts[0].strip().splitlines()
        app_lines = parts[1].strip().splitlines() if len(parts) > 1 else []

        uuid_users = {}
        for line in app_lines:
            cols = [c.strip() for c in line.split(",")]
            if len(cols) >= 4 and cols[0].startswith("GPU-"):
                uuid, _, user, mem = cols[0], cols[1], cols[2], cols[3]
                mem_gb = float(mem) / 1024 if mem.replace('.', '', 1).isdigit() else 0
                uuid_users.setdefault(uuid, []).append(f"{user}({mem_gb:.1f}G)")

        for line in gpu_lines:
            if "===TYPE:GPU===" in line or "," not in line:
                continue
            cols = [c.strip() for c in line.split(",")]
            if len(cols) >= 6:
                idx, uuid, name, util, used, total = cols[:6]
                short_name = name.replace("NVIDIA GeForce ", "")
                cards.append({
                    "node": f"{tag} ({alias})",
                    "device": f"GPU {idx}",
                    "model": short_name,
                    "util": int(float(util)),
                    "used": int(float(used)),
                    "total": int(float(total)),
                    "users": ", ".join(uuid_users.get(uuid, [])) or "-"
                })

    elif "===TYPE:NPU===" in output:
        lines = output.splitlines()
        npu_map = {}
        for i, line in enumerate(lines):
            mem_match = re.search(r"(\d+)\s*/\s*(\d+)", line)
            if mem_match and i > 0 and ("910" in lines[i - 1] or "310" in lines[i - 1]):
                used, total = int(mem_match.group(1)), int(mem_match.group(2))
                prev_cols = [c.strip() for c in lines[i - 1].split("|") if c.strip()]
                curr_cols = [c.strip() for c in line.split("|") if c.strip()]
                npu_id = prev_cols[0].split()[0] if prev_cols else "?"
                model = prev_cols[0].split()[-1] if prev_cols else "910B"
                util = int(curr_cols[1]) if len(curr_cols) > 1 and curr_cols[1].isdigit() else 0
                npu_map[npu_id] = {
                    "node": f"{tag} ({alias})",
                    "device": f"NPU {npu_id}",
                    "model": f"Ascend {model}",
                    "util": util,
                    "used": used,
                    "total": total,
                    "users": []
                }

        in_proc_section = False
        for line in lines:
            if "Process id" in line and "Process name" in line:
                in_proc_section = True
                continue
            if in_proc_section and "|" in line:
                cols = [c.strip() for c in line.split("|") if c.strip()]
                if len(cols) >= 4 and cols[0][0].isdigit():
                    npu_id = cols[0].split()[0]
                    proc_name = cols[2]
                    proc_mem = int(cols[3]) / 1024 if cols[3].isdigit() else 0
                    if npu_id in npu_map:
                        npu_map[npu_id]["users"].append(f"{proc_name}({proc_mem:.1f}G)")

        for item in npu_map.values():
            item["users"] = ", ".join(item["users"]) if item["users"] else "-"
            cards.append(item)

    return cards

def render_dashboard(console: Console, results: list[dict], only_free: bool = False):
    console.clear()
    table = Table(
        title="⚡ Lab Heterogeneous Cluster Monitor (GPU + Ascend NPU)",
        header_style="bold cyan",
        border_style="bright_black",
    )
    table.add_column("Server Node", style="bold white")
    table.add_column("Card", justify="center")
    table.add_column("Model")
    table.add_column("Util", justify="right")
    table.add_column("VRAM / HBM Usage", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Active Users / Procs", style="magenta")

    idle_count = 0
    total_count = 0

    for res in results:
        if res["error"]:
            table.add_row(f"{res['tag']} ({res['alias']})", "-", "-", "-", "-", "[bold red]OFFLINE[/bold red]", res["error"][:35])
            continue

        for c in res["cards"]:
            total_count += 1
            ratio = c["used"] / c["total"] if c["total"] else 0
            free_gb = (c["total"] - c["used"]) / 1024
            is_idle = ratio < 0.08 and c["util"] < 15

            if is_idle:
                idle_count += 1
                status = f"[bold green]● IDLE ({free_gb:.1f}G)[/bold green]"
            elif ratio < 0.75:
                status = f"[yellow]◐ PARTIAL ({free_gb:.1f}G)[/yellow]"
            else:
                status = "[red]✖ BUSY[/red]"

            if only_free and not is_idle:
                continue

            table.add_row(
                c["node"],
                c["device"],
                c["model"],
                f"{c['util']}%",
                f"{c['used']} / {c['total']} MB",
                status,
                c["users"],
            )

    console.print(table)
    console.print(Panel.fit(
        f"Summary: [bold green]{idle_count}[/bold green] / {total_count} cards completely idle.  "
        f"Config: [cyan]nodes.json[/cyan]",
        border_style="green" if idle_count > 0 else "yellow"
    ))

async def run_scan(console: Console, only_free: bool):
    nodes = load_nodes()
    with console.status("[bold green]Scanning cluster nodes via SSH..."):
        results = await asyncio.gather(*(query_node(n) for n in nodes))
    render_dashboard(console, results, only_free=only_free)

def main():
    parser = argparse.ArgumentParser(description="Multi-node GPU/NPU Cluster Monitor")
    parser.add_argument("--free", action="store_true", help="Only show idle cards")
    args = parser.parse_args()

    console = Console()
    is_double_clicked = getattr(sys, "frozen", False) and len(sys.argv) == 1

    while True:
        asyncio.run(run_scan(console, args.free))
        if not is_double_clicked:
            break
        choice = input("\n按 [R] 键刷新看板，按 [Enter] 直接退出: ").strip().lower()
        if choice != "r":
            break

if __name__ == "__main__":
    main()