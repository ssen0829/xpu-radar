# ⚡ xpu-radar

> Lightweight SSH-based CLI & Windows monitor for heterogeneous GPU (NVIDIA) and NPU (Huawei Ascend) lab clusters.  
> 轻量级异构算力集群监控看板（支持 NVIDIA GPU + 华为昇腾 Ascend NPU），免服务器部署，秒查空卡与占卡人。

## ✨ Features / 核心特性

- **Zero Server Invasion（零入侵部署）**：仅通过本地 SSH 并发轮询远程 `nvidia-smi` 与 `npu-smi`，无需在服务器上安装任何守护进程或额外依赖。
- **Heterogeneous Support（异构算力统一视图）**：同时支持 NVIDIA GPU（RTX 4090 / A100 等）与华为昇腾 Ascend NPU（910B 等）设备聚合展示。
- **At-a-Glance Status（直观状态与占卡人）**：自动区分空闲（IDLE）、部分占用（PARTIAL）与满载（BUSY），精确显示当前进程所属用户及显存占用。
- **Ready-to-Use Windows Binary（开箱即用）**：提供打包好的 Windows 独立可执行版本，无需配置本地 Python 环境，双击即用。

## 🚀 Quick Start / 快速上手

### 方式一：Windows 免安装版（推荐）

1. 前往 **[Releases (v1.0.0)](https://github.com/ssen0829/xpu-radar/releases)** 下载 `xpu-radar.zip` 并解压到任意纯英文目录。
2. 确保本地电脑已配置好到目标服务器的 SSH 免密登录（`~/.ssh/config`）。
3. 编辑解压目录中的 `nodes.json`，填入你的服务器 SSH 别名：
   ```json
   [
     {"alias": "gpu-node-1", "tag": ""},
     {"alias": "gpu-node-2", "tag": ""}
     {"alias": "npu-node-1", "tag": ""}
   ]
需要注意是的json文件中alias需要与ssh配置文件服务器的名字保持一致，tag可以随便取

### 方式二：Python 源码运行（适用于 Linux / macOS / Windows 开发者）
克隆仓库并安装依赖：

Bash
git clone [https://github.com/ssen0829/xpu-radar.git](https://github.com/ssen0829/xpu-radar.git)
cd xpu-radar
pip install -r requirements.txt
修改同目录下的 nodes.json 配置服务器别名（格式同方式一），然后在终端运行：

Bash
# 查看全部节点算力状态
python xpu_top.py
