# 思政智题云枢

思政智题云枢是一款面向思政题库建设、教学资料整理与题目数据标准化管理场景的桌面应用。项目聚焦题库录入、资料导入、题库查重、AI 解析生成与多格式导出，帮助用户将分散的文档资料逐步沉淀为可管理、可检索、可复用的题库资产。

项目支持手动新增题目，也支持从 `xlsx`、`docx` 等资料中批量导入题目；在导入过程中，可结合 AI 完成题号与题型识别、题目内容解析、题库查重以及题目解析生成。当前支持配置 `Deepseek`、`Kimi`、`Qwen` 等模型接口，并支持结合参考资料参与解析生成。

## 主要功能

- 手动新增题目
- 从 `xlsx` 导入题目
- 从 `docx` 导入题目
- AI 题号与题型解析
- AI 题目内容解析
- 题库查重
- AI 生成题目解析
- 导出 `Markdown`
- 导出 `PDF`
- 导出 `xlsx`

## 运行环境

- Python `3.11` 或更高版本
- Windows

## 依赖安装

```bash
pip install -r requirements.txt
```

当前主要依赖包括：

- `PyQt6`
- `openpyxl`
- `requests`
- `python-docx`
- `jieba`

## 启动方式

在项目根目录执行：

```bash
python main.py
```

## 打包与安装

项目当前提供两类产物：

- 目录版程序：`dist/思政智题云枢/`
- 安装包：`installer_output/sj-generator-setup-cn-dev.exe`

最简单的方式是直接运行：

```bat
build_installer.bat
```

如需指定版本号：

```bat
build_installer.bat 0.1.0
```

如需重新构建：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows_onedir.ps1 -Clean
```

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows_installer.ps1 -Clean -IsccPath "C:\Install\Inno Setup 6\ISCC.exe"
```

## 目录说明

- `main.py`：程序入口
- `sj_generator/`：项目源码
- `reference/`：参考资料与内置资源
- `installer_languages/`：安装包语言文件
- `installer_output/`：安装包输出目录
- `build_installer.bat`：一键打包安装包脚本
- `build_windows_onedir.ps1`：目录版构建脚本
- `build_windows_installer.ps1`：安装包构建脚本
- `installer_inno.iss`：Inno Setup 安装脚本

## 文档

- 使用手册：`docs/使用手册.md`

## Github

- 项目地址：[https://github.com/awsdfal7-arch/IdeoPivot](https://github.com/awsdfal7-arch/IdeoPivot)
