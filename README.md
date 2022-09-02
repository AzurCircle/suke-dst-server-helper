在线创建存档，欢迎测试: https://dst.suke.fun/

为方便管理自己的饥荒联机版服务器，写了这个工具。 

目前所有功能都在foralive.py文件中，其它项是为轻松配置世界所做的准备工作

# 现有功能
1. 闲置超时重置
   * 默认 24 小时
2. 满天数转无尽
   * 默认 40 天
3. 检测游戏更新
   * 默认 15 分钟
4. 备份聊天记录
   * 默认 2 分钟
5. 检测模组更新
   * 默认 15 分钟
   * 默认状态不能检测未公开 mod，需要填写 [Steam apikey](https://steamcommunity.com/dev/apikey) 以通过更高权限的 api 检测
6. 游戏崩溃自启
   * 默认 2 分钟
7. 多层世界支持

#### 可能添加
* 细分无人重置间隔，或添加在线时间检测
   * 不太必要
* 监测cpu负载，高负载过久重启饥荒服务器
   * 条件很难判定，且高负载时一般玩家也较多，重启非常影响体验

# 如何使用 
## 使用限制
1. 只支持Linux平台
2. 该工具与游戏进程交互是通过 Linux screen 完成的，确保你开启世界也是同样的方式。
   * 目前手动开启与自动脚本大多通过此方式

## 开始
### 准备工作
1. 打开文件，在文件最后修改自定义参数中 screen_dir 项为你的设置。
   * 在世界开启的情况下，输入命令`screen -ls`可查看相关信息
2. 打开文件，在文件最后关闭不需要的功能。默认全部开启
3. 仅有**自定义参数**可进行设置
4. 该工具会自行检测所需路径，不用填写。当然，如果需要，也可自行指定，工具会优先使用指定的路径。请使用绝对路径
5. 如果确定修改了 ugc_mod 目录，则需要填写自定义参数中 ugc_dir 项

### 开启命令
确保在开启之前，已经关掉之前开启的进程，如果不确定，首先执行[**关闭命令**](#关闭命令)

在foralive.py所在路径下执行

```bash
screen -L -Logfile foralive.log -dmS foralive python3 foralive.py
```

如果提示 screen 错误，说明使用的 screen版本 不支持自定义日志文件名称，使用这个命令即可

```bash
screen -L -dmS foralive python3 foralive.py
```

运行命令后会在当前路径下生成 foralive.log 或 screenlog.0 文件，打开该文件即可查看输出信息

### 关闭命令
任意路径下执行
```bash
screen -X -S foralive quit
```

# 其它内容
准备搭建一个网站，功能为：在线创建初始存档，包含所有必要内容，包括自定义世界设置与mod设置。设置项可随游戏或mod的更新自动更新
### 当前进度
已完成饥荒相关的准备工作
* 通过饥荒服务器lua文件自动解析**世界可设置项与其选项**
* 通过mod的modinfo文件自动解析**mod设置**。如果mod有中文支持，则选择中文
* 黑/白/管理 名单、cluster.ini、server.ini 等文件的设置项
* 饥荒表情的提取
### 完成
功能部分基本写好了，欢迎测试
地址: https://dst.suke.fun/