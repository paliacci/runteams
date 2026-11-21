# 邮件运营助理

在员工设置中连接 Gmail。对话可以交办检查新邮件，定时任务可以定期执行同一项工作。员工使用 `mail_followup_scan` 读取最近十封未读邮件，然后用 `mail_followup_triage` 保存判断。工作台显示需要跟进的邮件、截止时间、原因和待审核草稿。

草稿、推迟和完成状态保存在员工托管集合里。已有草稿保留在原来的集合，工作台可以读取并在首次操作时写入新集合。Gmail 只用于读取。

在已解压的作者 SDK 工作区，使用 Python 3.12 生成源码并打包。

```sh
python _runteams/sdk/examples/email-operations-assistant/package_example.py . ./email-operations-source
python runteams.py --project ./email-operations-source pack --output ./email-operations-assistant.zip
```
