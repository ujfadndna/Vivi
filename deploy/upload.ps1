# 上传脚本 - 在本机 PowerShell 运行
# 用法:
#   $env:HER_REMOTE = "root@your-server.example.com"
#   $env:HER_REMOTE_PORT = "22"
#   .\deploy\upload.ps1

$REMOTE = $env:HER_REMOTE
$PORT   = if ($env:HER_REMOTE_PORT) { $env:HER_REMOTE_PORT } else { "22" }
$PROJECT_ROOT = (Resolve-Path "$PSScriptRoot\..").Path

if (-not $REMOTE) {
    Write-Error "请先设置 HER_REMOTE，例如：`$env:HER_REMOTE='root@your-server.example.com'"
    exit 1
}

Write-Host "=== [1/4] 注册 SSH Key ===" -ForegroundColor Cyan
if (-not (Test-Path "$HOME\.ssh\id_rsa")) {
    ssh-keygen -t rsa -N "" -f "$HOME\.ssh\id_rsa"
}
$pubkey = Get-Content "$HOME\.ssh\id_rsa.pub"
Write-Host "请在远程终端运行：" -ForegroundColor Yellow
Write-Host "mkdir -p ~/.ssh && echo '$pubkey' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" -ForegroundColor White
Read-Host "`n按回车继续（注册完成后）"

Write-Host "`n=== [2/4] 上传项目代码 ===" -ForegroundColor Cyan
# 创建远程目录
ssh -p $PORT $REMOTE "mkdir -p /data/Her"

# 上传代码（排除大目录）
$items = @("app","docs","tests","scripts","deploy","third_party")
foreach ($item in $items) {
    $src = Join-Path $PROJECT_ROOT $item
    if (Test-Path $src) {
        Write-Host "  上传 $item ..."
        scp -P $PORT -r $src "${REMOTE}:/data/Her/"
    }
}
# 上传根目录白名单文件，避免误传 .env、日志、压缩包或本机素材
$rootFiles = @(
    ".env.example",
    "pyproject.toml",
    "pytest.ini",
    "requirements.txt",
    "requirements-agent.txt",
    "requirements-docker.txt",
    "requirements-flashhead.txt",
    "requirements-musetalk.txt",
    "requirements-segment.txt",
    "requirements-tts.txt",
    "requirements-tts-indextts.txt",
    "Dockerfile.api",
    "docker-compose.yml",
    "README.md",
    "AGENTS.md"
)
foreach ($name in $rootFiles) {
    $file = Join-Path $PROJECT_ROOT $name
    if (Test-Path $file) {
        scp -P $PORT $file "${REMOTE}:/data/Her/"
    }
}
Write-Host "  代码上传完成" -ForegroundColor Green

Write-Host "`n=== [3/4] 上传 MuseTalk 权重 (~9.3GB，需要几分钟) ===" -ForegroundColor Cyan
scp -P $PORT -r (Join-Path $PROJECT_ROOT "models") "${REMOTE}:/data/Her/"
Write-Host "  权重上传完成" -ForegroundColor Green

Write-Host "`n=== [4/4] 上传 Avatar 视频 ===" -ForegroundColor Cyan
ssh -p $PORT $REMOTE "mkdir -p /data/Her/workspace/avatar"
scp -P $PORT (Join-Path $PROJECT_ROOT "Video_input\default.mp4") `
    "${REMOTE}:/data/Her/workspace/avatar/default.mp4"
Write-Host "  Avatar 上传完成" -ForegroundColor Green

Write-Host "`n=== 上传全部完成 ===" -ForegroundColor Green
Write-Host "下一步：SSH 登录云端，运行 bash /data/Her/deploy/setup.sh" -ForegroundColor Yellow
