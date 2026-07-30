#!/usr/bin/env bash
# LearnFlow 一键启动脚本
# 使用: bash start.sh         (启动 + 自动打开浏览器)
#       bash start.sh stop   (停止)

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/venv"
PID_FILE="/tmp/learnflow-pids"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

banner() {
  echo -e "${BLUE}"
  echo "  _                   _____ _                "
  echo " | |   ___  ___ __ _|  ___| | _____      __ "
  echo " | |  / _ \/ __/ _\` | |_  | |/ _ \ \ /\ / /"
  echo " | |_|  __/ (_| (_| |  _| | | (_) \ V  V / "
  echo " |_____\___|\___\__,_|_|   |_|\___/ \_/\_/  "
  echo -e "${NC}"
  echo -e "${GREEN}AI 驱动的自适应学习平台${NC}"
  echo ""
}

check_deps() {
  # Python + venv
  if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo -e "${YELLOW}⚠  后端 venv 不存在，正在创建...${NC}"
    cd "$BACKEND_DIR"
    python3 -m venv venv
    source venv/bin/activate
    pip install -q -r requirements.txt
    echo -e "${GREEN}✅ 后端依赖安装完成${NC}"
  fi

  # .env
  if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo -e "${YELLOW}⚠  未找到 .env，从 .env.example 复制${NC}"
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo -e "${YELLOW}⚠  请编辑 backend/.env 填入你的 LLM_API_KEY${NC}"
  fi

  # Node modules
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo -e "${YELLOW}⚠  前端依赖未安装，正在安装...${NC}"
    cd "$FRONTEND_DIR"
    npm install --silent
    echo -e "${GREEN}✅ 前端依赖安装完成${NC}"
  fi
}

start_services() {
  echo -e "${BLUE}━━━ 启动后端 (端口 8000) ━━━${NC}"
  cd "$BACKEND_DIR"
  source venv/bin/activate
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
  BACK_PID=$!
  echo $BACK_PID > "$PID_FILE"

  echo -e "${BLUE}━━━ 启动前端 (端口 5173) ━━━${NC}"
  cd "$FRONTEND_DIR"
  npm run dev &
  FRONT_PID=$!
  echo $FRONT_PID >> "$PID_FILE"

  echo ""
  echo -e "${GREEN}✅ LearnFlow 已启动！${NC}"
  echo ""
  echo -e "   ${BLUE}前端:${NC}  http://localhost:5173"
  echo -e "   ${BLUE}后端:${NC}  http://localhost:8000"
  echo ""
  echo -e "   ${YELLOW}停止:${NC}  bash start.sh stop"
  echo ""

  # Auto-open browser after a short delay
  (sleep 3 && open http://localhost:5173) &
}

stop_services() {
  if [ -f "$PID_FILE" ]; then
    echo -e "${YELLOW}正在停止 LearnFlow...${NC}"
    while read -r pid; do
      kill "$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
    echo -e "${GREEN}✅ 已停止${NC}"
  else
    pkill -f "uvicorn app.main:app" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true
    echo -e "${GREEN}✅ 已停止 (清理模式)${NC}"
  fi
}

case "${1:-}" in
  stop)
    stop_services
    ;;
  restart)
    stop_services
    sleep 1
    banner
    check_deps
    start_services
    ;;
  *)
    banner
    check_deps
    start_services
    ;;
esac
