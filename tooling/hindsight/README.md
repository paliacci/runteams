# 旧版本机资产偏好的导入

RunTeams 将资产偏好和上传的文字资料保存在个人设备资料库的 SQLite 数据库。新安装直接使用现有的 Agent CLI、SQLite 和 PDFium。

从已配置 Hindsight 的旧版升级时，保留原有的本机服务和 `RUNTEAMS_HINDSIGHT_KEY_FILE`。首次读取每个资产的偏好时，RunTeams 会把旧正文导入该资产的 SQLite 记录。导入成功后，该资产的更正和清空均写入 SQLite。尚有资产未导入时请保留原数据库。

如需读取旧数据库，可以使用原环境启动旧服务：

```sh
bash tooling/hindsight/service.sh serve
```
