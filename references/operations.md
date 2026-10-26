# 本地操作

命令中的路径是示意，替换为当前实际绝对路径。Python 3.10+，无第三方依赖。

```bash
python3 /path/to/material-collector/scripts/library.py init --root /path/to/new-library --config /path/to/config.json
python3 /path/to/material-collector/scripts/library.py ingest --root /path/to/new-library --record /path/to/record.json
python3 /path/to/material-collector/scripts/library.py status --root /path/to/new-library
python3 /path/to/material-collector/scripts/library.py verify --root /path/to/new-library
```

record 格式见 `assets/record.example.json`。files 是已经暂存并检查的本地文件绝对路径；无附件也可保存来源和摘要。作者和日期未知时留空，不代填。

同一规范 URL 再运行不会创建第二条；同一条新增附件会追加；相同哈希在不同条目间共享本地附件。URL 保留查询参数，只移除片段；跟踪参数或转载导致的语义重复由 Agent 判断，记录关联，不擅自删掉有意义的参数。已有条目的摘要和标题不自动覆盖，人工编辑后继续保留。

库结构：

```text
library/
  .collector/config.json     用户配置
  .collector/index.json      条目、附件哈希、同步状态
  items/                     每条素材的 Markdown 笔记
  attachments/               按哈希保存的原文件
  INDEX.md                   自动生成，不放人工笔记
  HANDOFF.md                 接手入口
  reports/                   Agent 写的运行记录
  preferences.md             用户反馈与已采用规则
  sources-candidates.md      未启用的来源建议
```

后三项按实际需要由 Agent 建立，不制造空报告。Obsidian 的普通 Markdown 链接和相对图片路径不依赖额外插件。

同步结果由 Agent 回读后写证据 JSON，再记录：

```bash
python3 /path/to/material-collector/scripts/library.py sync --root /path/to/new-library --id MC-实际编号 --target eagle --status verified --evidence /path/to/evidence.json
```

证据格式：`{"remote_refs":["真实远端标识"],"readback_at":"实际ISO时间","asset_sha256":["索引内的附件哈希"],"scope":"实际同步范围","note":"实际核验方式"}`。

若飞书仅同步摘要，仍列出已核对的本地附件版本哈希，并在 scope 明确 `summary-only`，表示该版本的摘要已同步，不能声称附件上传成功。报告必须展示 scope。资产列表用于把证据绑定到本地版本；脚本不会自行证明远端写入，不能以通过字段检查冒充真实回读。

写入使用原子替换与单库写锁。遇到 write.lock 时停止并检查是否有进程在写；确认中断进程已经结束后才移除遗留锁。不要并行写同一个库。中断留下的孤立附件不影响已记录内容；重跑原 record 可继续。索引是主记录，重新 ingest 可补建缺失笔记。不要手工修改附件路径，不自动清空或删除孤立文件。
