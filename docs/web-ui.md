# 本机 Web 控制台 / Local Web UI

在浏览器里运行 paper-reviewer，无需记命令行参数。真实润色仍由 [`run.py`](../run.py) 或 [`run_demo.py`](../run_demo.py) 子进程执行。

## 启动

```powershell
cd paper_reviewer
.\scripts\conda_run.ps1 python -m pip install fastapi "uvicorn[standard]"
.\scripts\conda_run.ps1 python web_app.py
```

浏览器打开：**http://127.0.0.1:7860/**

可选参数：

```powershell
python web_app.py --host 127.0.0.1 --port 7860
```

默认只监听本机 `127.0.0.1`，不对外网开放。

## 页面说明

| 区域 | 作用 |
|------|------|
| 主页 | 统一入口，可跳转到润色工作台、修改配置、日志中心 |
| 润色工作台 | 输入/输出 TeX 路径、YAML 配置、模式、迭代次数、实时日志与输出预览 |
| 修改配置 | 读取和保存 `config/`、`private/`、`examples/` 下的 YAML |
| 日志中心 | 查看最近的 `logs/run_*.log` |

**路径规则：** 与 CLI 相同，相对路径以**仓库根目录**为基准（不是 `private/` 目录）。

## 常用操作

1. **快速试跑（无 LLM）：** 勾选「Mock 演示」，输入 `sample_manuscript.tex`，配置用 `config/local.example.yaml`（若尚无 `config/local.yaml`）。
2. **真实润色：** 取消 Mock，配置选 `private/run_config.yaml` 或 `config/local.yaml`，填好 `input_path` / `output_path`。
3. **术语表：** 运行后右侧「术语表」页可查看 `private/glossary.merged.yaml`。
4. **修改配置：** 从主页进入「修改配置」，选择 `config/local.yaml` 或 `private/run_config.yaml`，编辑后保存。

## 路由

| 路由 | 页面 |
|------|------|
| `#/home` | 主页 |
| `#/run` | 润色工作台 |
| `#/config` | 修改配置 |
| `#/logs` | 日志中心 |

## 与 bat / CLI 的关系

| 方式 | 适用 |
|------|------|
| `web_app.py` | 可视化配置、看日志、预览输出 |
| `private/run_my_paper.bat` | 双击一键跑固定配置 |
| `python run.py ...` | 脚本、CI、完全可控 |

三者共用同一套 YAML 与 `run.py` 逻辑，互不冲突。

## 常见问题

**页面打不开**  
确认终端里 `web_app.py` 仍在运行，且访问的是 `127.0.0.1` 而不是局域网 IP。

**提示配置文件不存在**  
复制 `config/local.example.yaml` 为 `config/local.yaml`，或使用 `examples/run_config.example.yaml` 复制到 `private/run_config.yaml`。

**同时只能跑一个任务**  
避免两个长任务同时占用 Ollama；需停止时点「停止」。

**输出路径在仓库外**  
例如 `../paper_reviewer_data/output_run.tex` 可以，只要本机路径存在且可写。
