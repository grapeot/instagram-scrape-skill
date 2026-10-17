# instagram-scrape-skill

instagram-scrape-skill 用来归档你自己的 Instagram 账号中的媒体文件。它使用 Chrome DevTools Protocol (CDP) 将AI编程Agent挂到真实的Chrome session上，抓取你在浏览自己的主页时，Instagram网页app自己请求的GraphQL响应(payload)，然后将其解析成结构化的持久化索引，并支持可选的浏览器内下载。整个过程不会提取/存储任何Cookie, token, .env 或登录凭据。

## 为什么会有这个仓库

这个项目的灵感来源于 AI Builders 课程的课后作业。AI Builders 课程的一个 office-hours 直播演示的作业是：打开浏览器 DevTools，滚动浏览自己的 Instagram 个人主页，把请求记录下来保存成 HAR 文件，然后让 AI 从 HAR 文件中抓取图片 URL，写出多线程下载代码，把图片保存到本地文件夹。

在后续的 live class 上，介绍了这样一个思路：如果一个任务第二次被你做，那就把它变成一个 skill file。skill file 是一种 provider-neutral（不绑定任何厂商）的 Markdown 文档，它用简单、直白的语言定义任务的目标、验收标准、以及要注意的踩坑点。同时通过 progressive disclosure（渐进式披露）的机制给 AI agent 一个索引，让它可以按需发现。这样，一个全新的 AI agent 就可以用非常简单的 prompt 来复现整个任务。

这个仓库同时实现了这两个意义：它既是那个最初作业的 agent-native 版本（Agent 完成从抓取、解析到存档的全流程，不再需要手动导出的 HAR），也是一则完整的 skill file 提炼示例（含可运行的代码、提炼后的 skill file 和诚实的边界说明）。

## 工作原理

```text
+------------------------------------------------------------------------+
| 1. CAPTURE (Real Chrome + Playwright CDP listener)                     |
|    Human logs in -> Agent scrolls grid -> Web app POSTs /api/graphql   |
|    Protocol-level page.on("response") writes raw payloads to disk      |
+------------------------------------------------------------------------+
                                   |
                                   v
+------------------------------------------------------------------------+
| 2. PARSE (Dialect-aware GraphQL extractor)                             |
|    Detects /api/graphql connection edges vs /graphql/query nodes       |
|    Extracts max-width images, max-height videos, and carousel items    |
+------------------------------------------------------------------------+
                                   |
                                   v
+------------------------------------------------------------------------+
| 3. ARCHIVE (Deduplicated JSONL index + optional in-browser download)   |
|    Merges records by (shortcode, image_url) -> media_index.jsonl       |
|    Optional page-context fetch(mediaUrl) -> base64 over CDP -> disk    |
+------------------------------------------------------------------------+
```

**捕获（Capture）。** 工具用 `--remote-debugging-port=9223`、`--user-data-dir=<fresh temp dir>`、`--no-first-run` 和 `--no-default-browser-check` 启动一个 Chrome，打开 `instagram.com` 让用户手动登录。然后 Python 监听器通过 Playwright 的 `chromium.connect_over_cdp("http://localhost:<port>")` 挂接到浏览器，并注册协议级的 `page.on("response")` 和 `page.on("request")` 处理函数；这些处理函数在页面刷新后依然有效，同时会过滤掉统计分析噪音和静态资源。实际的数据请求完全由浏览器自己发起：Agent 仅通过 `page.evaluate` 以大约 2 秒的间隔执行 `window.scrollBy` 来驱动分页加载，每一次数据请求都由 Instagram 网页应用自己用 `POST` 发到 `https://www.instagram.com/api/graphql`。不管响应声明的 Content-Type 是什么，每个原始 API 响应体（大约 300 KB 的 JSON）都被写入磁盘——因为分页响应声明的是 `content-type: text/javascript`。

**解析（Parse）。** 解析器读取捕获到的载荷，并在两种并存的 GraphQL 方言（dialect）之间自动识别：一种是位于 `data.xdt_api__v1__feed__user_timeline_graphql_connection.edges[].node` 下的个人主页分页载荷，另一种是来自 `/graphql/query`、带有扁平 `display_url` 和 `video_url` 字段的页面加载载荷。解析器从每个节点中提取 `code`、`taken_at`、`caption.text` 和 `media_type`（`1` = 照片，`2` = 视频，`8` = 多图轮播 carousel），将 `carousel_media[]` 相册展开为独立条目，图片从 `image_versions2.candidates[]` 中选取最大宽度版本，视频从 `video_versions[]` 中选取最大高度版本，并构造帖子固定链接 `https://www.instagram.com/p/<code>/`。

**归档（Archive）。** 解析后的页面记录被合并为一个以 `(shortcode, image URL)` 为键的去重媒体索引文件（`media_index.jsonl`），并且从当前会话的个人主页 URL（而不是载荷中的字符串）推断出已登录的账号身份。如果传入 `--download`，则 Agent 会在已登录的浏览器上下文中执行 `fetch(mediaUrl)`（在这里，带签名的 CDN URL 支持跨域访问，即 CORS-open），通过 CDP 通道将二进制数据（blob）以 base64 编码读回并解码到磁盘，最后终止监听器和 Chrome 进程，同时删除临时用户配置目录。

## 快速开始

1. 使用 `uv` 创建虚拟环境，并以可编辑模式（editable mode）安装本包：

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

2. 针对你自己的 Instagram 账号运行 `ig-scrape archive`：

```bash
ig-scrape archive --username example_user --max-items 120 --max-pages 10 --download --out ./output
```

这时，它会用一个新的临时config目录打开一个新的Chrome窗口访问`instagram.com`。你需要在这个窗口里登录并且自己处理所有的checkpoint和2FA提示。登录后，它会探测会话状态，滚动个人主页的网格，将抓取的GraphQL响应保存在`raw_pages/`文件夹下，将去重后的索引写入`media_index.jsonl`，同时将媒体文件下载到`media/`文件夹下。

3. 离线重新解析单个已归档的响应载荷，或将索引导出为 JSON 或 CSV：

```bash
# Offline re-parse of one archived GraphQL response payload
ig-scrape parse --page ./output/example_user/raw_pages/page_0001.json --out ./reparse_out

# Export the JSONL index to flat JSON or CSV
ig-scrape export --index ./output/example_user/media_index.jsonl --format json
ig-scrape export --index ./output/example_user/media_index.jsonl --format csv
```

## 输出结构

运行`ig-scrape archive`会在`--out`目录下生成类似这样的目录结构：

```text
output/
└── example_user/
    ├── media_index.jsonl
    ├── raw_pages/
    │   ├── 20261017T083012Z_page_0001.json
    │   └── 20261017T083015Z_page_0002.json
    └── media/
        ├── CLPf-i2Pb0k_01.jpg
        └── CLPf-i2Pb0k_02.mp4
```

`media_index.jsonl` 中的每一行都是一个固定的11个字段组成的JSON对象（`username`, `code`, `permalink`, `type`, `taken_at`, `caption`, `image_url`, `video_url`, `carousel_media_count`, `first_seen`, `source_page`）。其中`source_page`是回指已被归档的原始载荷文件，因此每一行都可以离线重新解析。对于多图轮播（carousel）的帖子，则会生成一个`type`为"carousel"的父记录，和每个轮播项分别对应的记录。例如（虚构数据）：

```json
{
  "username": "example_user",
  "code": "CLPf-i2Pb0k",
  "permalink": "https://www.instagram.com/p/CLPf-i2Pb0k/",
  "type": "photo",
  "taken_at": 1690000000,
  "caption": "Sample caption from archived profile post.",
  "image_url": "https://cdn-images.example/v/t51.29350-15/CLPf-i2Pb0k_1440x1085.jpg?oh=fake_sig&oe=00000000",
  "video_url": null,
  "carousel_media_count": null,
  "first_seen": "2026-10-17T08:30:12Z",
  "source_page": "raw_pages/20261017T083012Z/page_0001.json"
}
```

## 提炼出的技能文件

可复用的Agent技能文件在 `skills/instagram-scrape/SKILL.md`，体现了课程中"将重复任务提炼为与模型厂商无关的Markdown规范"的方法。它向AI编程Agent提供了明确的目标、CDP连接工作流、验收标准和7个经过实测验证的实操踩坑点，使Agent无需通过试错重新摸索：分页响应以`content-type: text/javascript`返回，若使用JSON MIME过滤器会被静默丢弃；两种并存的GraphQL方言（`/api/graphql`与`/graphql/query`）；使用协议级`page.on("response")`捕获，而非在页面刷新后就会失效的`window.fetch`猴子补丁（monkey-patch）；按会话带时间戳的文件编号机制，防止重启监听器时覆盖早先捕获的文件；从会话个人主页URL推导用户身份，而非误取载荷中内嵌的推荐账号用户名；将CDP端口参数化并为每次会话分配全新的`user-data-dir`，避免端口冲突及旧配置目录引发的单点登录（SSO）循环；以及退出时强制清理监听器、Chrome进程和临时配置目录。

## 局限性与客观说明

- **带签名的 CDN URL 会过期：** 直接的 `image_url` 和 `video_url` 链接带有短期签名，会在数天内过期。因此，索引将 CDN URL 视为临时链接，并记录帖子固定链接（`https://www.instagram.com/p/<code>/`）加捕获时间戳作为持久化标识；如果需要保存本地媒体文件，请在归档时传入 `--download`。
- **登录墙仅限人工处理：** 身份认证、安全验证（checkpoint）和双重认证（2FA）严格由人工完成。如果工具在会话探测或滚动浏览期间检测到登录墙，会立即拒绝执行并停止运行。
- **服务条款边界说明：** Meta 的服务条款禁止未经授权的自动化采集。以接近人类的操作节奏归档本人账号内容是风险最低的使用方式；本仓库明确不作更宽泛的合规承诺，不提供批量采集功能，也不在离线环境下存储或复用任何签名 URL 或指纹绕过技巧。
- **v0 版本范围：** 本工具仅针对你本人的个人主页网格（照片、视频以及展开后的多图轮播条目）。快拍（Stories）、Reels 标签页、收藏夹（Saved collections）、大规模抓取循环、多用户名扩散抓取（username fan-out）以及匿名抓取模式均在设计上明确排除。

## 仓库目录结构

```text
instagram-scrape-skill/
├── README.md
├── README.zh-CN.md
├── LICENSE
├── pyproject.toml
├── docs/                   # prd / rfc / working / test
├── skills/
│   └── instagram-scrape/
│       └── SKILL.md        # the distilled agent skill
├── scripts/
│   └── ig-scrape           # CLI entrypoint
├── src/
│   └── ig_scrape/
│       ├── __init__.py
│       ├── cli.py
│       ├── capture.py      # CDP session: launch, attach, scroll, capture
│       ├── parser.py       # dialect-aware payload -> media records
│       └── archive.py      # merge, export, in-browser download
└── tests/
    ├── fixtures/           # sanitized GraphQL payload fixtures
    ├── test_parser.py
    └── test_archive.py
```

## 许可证

MIT 许可证。完整文本见 `LICENSE`。
