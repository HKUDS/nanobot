FROM node:18-alpine

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY package*.json ./

# 安装依赖
RUN npm ci --only=production

# 复制源代码
COPY . .

# 构建应用
RUN npm run build

# 安装serve来提供静态文件
RUN npm install -g serve

# 暴露端口
EXPOSE 3001

# 启动命令
CMD ["serve", "-s", "dist", "-l", "3001"]