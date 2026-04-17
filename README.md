# Web2Apk Web

把任意网站打包成 Android APK 的在线服务。

- 输入网址 → 点击构建 → 下载 APK
- 完全 Docker 化，JDK / Android SDK / Gradle 全部预装在镜像内
- 首次构建约 30 秒~2 分钟（视网络与服务器性能而定）
- 支持 GitHub Actions 自动构建镜像 + Render 免费部署

## 快速开始（本地 Docker）

```bash
cd web2apk-web
docker build -t web2apk-web .
docker run -p 8000:8000 web2apk-web
```

然后打开 http://localhost:8000 即可使用。

## 部署到线上

### 1. 推送到 GitHub

如果你还没有创建仓库，先在 GitHub 上新建一个空仓库（例如 `你的用户名/web2apk-web`），然后：

```bash
cd web2apk-web
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/你的用户名/web2apk-web.git
git push -u origin main
```

推送后，GitHub Actions 会自动构建 Docker 镜像并推送到 `ghcr.io/你的用户名/web2apk-web:latest`。

### 2. 部署到 Render（推荐免费方案）

1. 登录 [Render](https://render.com)
2. 点击 **New +** → **Web Service**
3. 选择你的 GitHub 仓库 `web2apk-web`
4. Render 会自动识别 `render.yaml` 并使用 Docker 部署
5. 等待 5~10 分钟（Docker 镜像构建较慢），即可获得公开访问链接

> Render 免费实例会在 15 分钟无请求后休眠，首次访问可能需要等待唤醒（约 30 秒）。

## 项目结构

```
.
├── Dockerfile                 # 预装 JDK + Android SDK + Gradle 的镜像
├── web2apk.py                 # 核心构建脚本
├── app/
│   ├── main.py                # FastAPI 后端
│   ├── static/index.html      # 前端页面
│   └── requirements.txt       # Python 依赖
├── .github/workflows/docker.yml   # GitHub Actions 自动构建镜像
├── render.yaml                # Render 一键部署配置
└── README.md
```

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/build` | POST | 提交构建任务，返回 `job_id` |
| `/api/status/{job_id}` | GET | 查询构建状态 |
| `/api/download/{job_id}` | GET | 下载构建好的 APK |

## 注意事项

- 由于免费服务器资源有限，**同时只允许 1 个构建任务运行**，其余请求会自动排队。
- 构建结果仅在服务器上保留 **24 小时**，请及时下载。
- 如果构建失败，可在前端查看最后一段构建日志排查问题。
