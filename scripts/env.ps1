# Dot-source this before running uv in this project:   . .\scripts\env.ps1
#
# The project venv lives outside the project folder because this checkout sits
# under a long path and Windows' 260-character limit breaks imports from a
# venv created inside it. Once the project lives at a short path (e.g.
# C:\code\gametl) this is unnecessary and `uv sync` can use .venv as usual.
$env:UV_PROJECT_ENVIRONMENT = Join-Path $HOME ".venvs\gametl"
Write-Host "UV_PROJECT_ENVIRONMENT=$env:UV_PROJECT_ENVIRONMENT"
