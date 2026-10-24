# BB Deadline Notifier（模板）

南方科技大学 Blackboard（bb.sustech.edu.cn）作业截止日期邮件提醒，**纯云端运行**——你的电脑不需要安装任何东西。

## 推荐安装方式：一键向导

打开 **[一键部署向导](https://another1332.github.io/bb-deadline-notifier-template/setup.html)**，
按提示填入 QQ 邮箱授权码、BB 日历链接和一个临时 GitHub 令牌，点一下按钮即完成部署。
不填学校密码 = 纯 ICS 模式；填上 = 全保真模式（课程名 + 已提交分流）。

## 手动安装（不想用向导的话）

1. 点击本页面绿色按钮 **"Use this template" → "Create a new repository"**，建一个 **Private** 仓库。
2. 仓库 Settings → Secrets and variables → Actions → Secrets，逐个添加：

   | Secret | 值 |
   |---|---|
   | `ICS_URL` | BB → 日历 → Get External Calendar Link（`webcal://` 改 `https://`） |
   | `SMTP_USER` / `SMTP_PASS` | 个人 QQ 邮箱地址 / SMTP 授权码（设置 → 账户 → 开启 SMTP） |
   | `MAIL_TO` | 收件邮箱（建议学校企业邮，有手机推送） |
   | `SCHOOL_PASSWORD` | 学校统一认证密码（**选填**；不填 = 纯 ICS 模式） |

3. 若填了 `SCHOOL_PASSWORD`，在同一页 **Variables** 里加 `SUSTECH_SID` = 你的学号。
4. Actions 页面若提示 workflows 被禁用，点 "I understand my workflows, go ahead and enable them"。
5. Actions → notify → Run workflow → mode 选 `escalate`，首次运行验证。收件箱应收到第一封邮件。

## 邮件策略

- **每日日报**（北京时间 08:00）：未来 14 天内所有**未提交**作业汇总；全部交清则不发（静默 = 安全）。
- **分档升级提醒**（每天 08:10 / 14:00 / 20:00 检查）：作业剩余时间跨进 48h / 24h / 12h 窗口时各提醒一封；
  **已提交的也会提醒**（标注「已提交·请复核」，防状态误标/漏交）；老师顺延 deadline 会重新触发。
- 认证层故障时自动降级为 ICS 数据源，邮件带 `[降级]` 前缀（无课程名、未分流），提醒不断电。
- 可选：Variables 加 `ENABLE_GRADES=1` 开启出分提醒；`TIER_HOURS`、`LOOKAHEAD_DAYS` 同理可调。

## 不要 GitHub 的零安装替代

把 ICS 链接直接订阅进手机日历（iPhone：设置 → 日历 → 添加订阅日历），零维护；
代价是没有邮件汇总、提交分流，同步也略延迟。

## 说明

- 私有仓库的 Actions 免费额度为每月 2,000 分钟，本工具每天 4 次运行约消耗 120 分钟/月。
- 仓库必须保持 **Private**：`state/` 中含有加密的会话缓存。
- 基于 [sustech-cli](https://github.com/wormforce/sustech-cli)（PolyForm 非商业许可，请勿用于收费服务）。
- 本项目不做、也不接受任何验证码自动绕过；登录触发验证码时自动降级并在 12 小时后重试。
