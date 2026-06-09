# crawler/ — 全自动搜索下载（已废弃）

## 结论：全自动不可行

经过12条技术路径的穷举测试，2026年6月所有全自动路径均已封堵。

## 尝试过的路径

| # | 方案 | 结果 | 根因 |
|:---:|------|:---:|------|
| 1 | QQ搜索API → bookId | ✅ | `so.html5.qq.com` 直连，6/6命中 |
| 2 | QQ章节API `android.reader.qq.com` | ❌ | 全部504，端点已下线 |
| 3 | QQ H5页面 `novel.html5.qq.com` | ❌ | React SPA，无章节HTML |
| 4 | Playwright QQ阅读翻页 | ❌ | 检测到非QQ浏览器→跳转下载页 |
| 5 | biqugequ直接搜索 HTTP | ❌ | POST表单JS混淆 |
| 6 | biqugequ搜索 Playwright | ❌ | 输入框JS动态生成 |
| 7 | xbiquge搜索 Playwright | ❌ | 验证码（`placeholder=请输入验证码`） |
| 8 | Bing搜biquge URL | ❌ | Bing过滤器biquge链接 |
| 9 | 百度搜biquge URL | ❌ | 百度屏蔽biquge域名 |
| 10 | biquge镜像(5200/99/001等) | ❌ | ConnectionError/JS混淆反爬 |
| 11 | 番茄小说API | ❌ | `invalid client`（需设备指纹） |
| 12 | Fanqie-novel-Downloader | ❌ | Electron GUI软件，非库 |

## 根因分析

- **平台封堵**：QQ/番茄/起点均升级签名校验+SPA架构，纯HTTP爬虫不可行
- **biquge生态崩溃**：主力域名全需JS/验证码，镜像站大面积失效
- **搜索引擎屏蔽**：百度/Bing均过滤盗版站链接
- **单人资源边界**：代理不稳定、无商业反爬服务、8GB显存无法跑重量级OCR

## 保留下来的最小工具

- `data/download_queue.json` — 下载队列模板
- `d:/Code/NovelDownloader/` — 手动下载工具（粘贴URL→批量下载）

## 工作流

纯手动：浏览器搜biqugequ.org → 复制目录页URL → 填到download_queue.json → NovelDownloader下载。
