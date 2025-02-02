#!/usr/bin/python3
# -*- coding: utf-8 -*-
# 21.05.10 by suke
# version 22.01.28

"""
在本文件路径下运行开启指令。括号内内容，不带括号(screen -L -Logfile foralive.log -dmS foralive python3 foralive.py)
关闭指令(screen -X -S foralive quit)
开启后查看同目录下foralive.log日志文件了解 是否开启成功 与 运行情况

在运行前要做的有两件事：1.确保自定义参数中 screen_dir 项准确无误；2.关闭不需要的功能

需要关闭某功能请查看文件最底，使用前务必按需求设置
如需自定义参数，在自定义参数中修改

1.闲置超时重置          默认 24 小时
2.满天数转无尽          默认 40 天
3.检测游戏更新          默认 15 分钟
4.备份聊天记录          默认  2 分钟
5.检测mod更新          固定 15 分钟左右
6.游戏崩溃自启          默认  2 分钟
7.多层世界支持

    待做     怎么才能做到自动识别世界对应的screen作业名呢
            30天前12小时，30天后24小时  无人重置  # 不太必要
            监测cpu负载，高负载过久重启  # 条件很难判定，等好的想法


"""
import gc
# import logging
from inspect import getsourcefile
from json import loads
from os import listdir, mkdir, remove, rename, sep, stat, walk, killpg
from os.path import abspath, basename, dirname, exists, expanduser, isdir, join as pjoin, sep
from re import findall, search, sub
from shutil import copyfile, copytree, rmtree
from signal import SIGTERM
from subprocess import PIPE, Popen, TimeoutExpired
from threading import Timer
from time import localtime, sleep, strftime, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def active_time():
    # 获取游戏目录下，所有玩家meta快照文件的最后修改时间。利用玩家快照文件进行判断，不受服务器重启影响。
    global path_cluster, world_list
    try:
        mtimes = []
        path_worlds = [pjoin(path_cluster, world) for world in world_list]
        for path_world in path_worlds:
            for rt, dirs, files in walk(str(path_world)):  # 不转str，就提示下面的'.meta'应为'bytes'，为什么
                if len(basename(rt)) == 12:
                    for i in files:
                        if '.meta' in i:
                            mtimes.append(stat(pjoin(rt, i)).st_mtime)
        return sorted(mtimes)[-1] if mtimes else 0
    except Exception as e:
        print(now(), 'activity_time函数出错')
        print(now('blank'), e)
        return 0


def table_dict(data_raw):  # 把meta文件的table转为dict
    data_raw = data_raw[data_raw.find('{'):data_raw.rfind('}') + 1]
    data_raw = data_raw.replace('=', ':').replace('["', '"').replace('"]', '"')
    data_raw = sub(r'(?P<item>[\w.]+)(?=\s*:)', r'"\g<item>"', data_raw)  # 键加 ""
    data_raw = sub(r',(?=\s*?[}|\]])', r'', data_raw)  # 删去与结束符"}]"之间无数据的逗号
    data_raw = data_raw if data_raw else '{}'
    data_dict = loads(data_raw)
    return data_dict


def meta_info(path_meta):
    info = {}
    with open(path_meta, 'r', encoding='utf-8') as f:
        data = f.read()
    meta_dict = table_dict(data)
    day = meta_dict.get('clock', {}).get('cycles', -1) + 1  # 当前天数
    passed_season = meta_dict.get('seasons', {}).get('elapseddaysinseason', 0)  # 季节已过天数
    phase = meta_dict.get('clock', {}).get('phase', '')  # 当前阶段
    remaining_season = meta_dict.get('seasons', {}).get('remainingdaysinseason', 0)  # 季节剩余天数
    remaining_time = meta_dict.get('clock', {}).get('remainingtimeinphase', 0)  # 阶段剩余时间
    season = meta_dict.get('seasons', {}).get('season', '')  # 当前季节
    segs = meta_dict.get('clock', {}).get('segs', {})  # 阶段分段信息

    season = {'spring': '春', 'summer': '夏', 'autumn': '秋', 'winter': '冬'}.get(season, '')
    season = f'{season} {passed_season + 1}/{passed_season + remaining_season}'
    segs_list = [segs.get(i, 0) * 30 for i in ('day', 'dusk', 'night')]
    passed_time = sum(segs_list[:{'day': 0, 'dusk': 1, 'night': 2}.get(phase, 0) + 1]) - remaining_time  # 当天已过时间
    info['day'] = day
    info['passed_time'] = passed_time
    info['season'] = season
    return info


def survival_days(world=None):
    global path_cluster, master_name
    world, mode = [world or master_name], (0, 1)[world is None]
    day_info, newest_time, newest_path = {'day': 0, 'passed_time': '', 'season': ''}, 0, ''
    try:
        meta_files = []
        for rt, dirs, files in walk(path_cluster):  # 检索存档内的快照文件，保存路径和修改时间
            if len(basename(rt)) == 16 and rt.split(sep)[-4] in world:
                for file in files:
                    if file.endswith('.meta'):
                        file_path = pjoin(rt, file)
                        file_mtime = stat(file_path).st_mtime
                        meta_files.append((file_path, file_mtime))
        if meta_files:  # 筛选出最新快照，返回天数信息、修改时间或路径
            meta_file = sorted(meta_files, key=lambda x: x[1])[-1]
            day_info = meta_info(meta_file[0])
            newest_path = meta_file[0]
            newest_time = meta_file[1]
    except Exception as e:
        print(now(), f'survival_days函数出错：{e}')
    finally:
        return (*day_info.values(), newest_time) if mode else newest_path


def reset():
    global path_cluster, path_dst_bin, time_to_reset
    path_clu_ini = pjoin(path_cluster, 'cluster.ini')
    reset_time = time_to_reset * 60 * 60
    t = 3600
    try:
        print(now(), '检测是否需要重置')
        act_time = active_time()  # 获取最后活动时间
        if not act_time:
            print(now('blank'), '未找到玩家快照文件')
            print(now('blank'), '不需要重置')
            t = reset_time
            return

        print(now('blank'), '最后活动时间：' + now(act_time))
        if reset_time > time() - act_time:  # 判断是否超过指定时间无人上线
            print(now('blank'), '不需要重置')
            t = reset_time - (time() - act_time)
            return
        # 修改设置，改为生存模式
        with open(path_clu_ini, 'r', encoding='utf-8') as f, open(path_clu_ini + '.temp', 'w+', encoding='utf-8') as f2:
            newdata = sub(r'(\n\s*game_mode\s*=\s*)[\d\D]+?(\n)', r'\g<1>survival\g<2>', f.read())
            f2.write(newdata)
        remove(path_clu_ini)
        rename(path_clu_ini + '.temp', path_clu_ini)

        print(now('blank'), '开始重置世界')
        running_list = [i[0] for i in zip(world_list, running(world_list)) if i[1]]  # 记录正在运行的世界，最后开启
        for world_name in running_list:  # 删除所有快照文件
            path_save = pjoin(path_cluster, world_name, 'save')
            if exists(path_save):
                rmtree(path_save)
        stop_world(running_list)
        start_world(running_list)

        t = reset_time
    except Exception as e:
        print(now('blank'), 'reset函数出错')
        print(now('blank'), e)
    finally:
        t = max(t, 60)
        print(now('blank'), f'下次检测时间：{now(time() + t)}')
        Timer(t, reset).start()  # 间隔t秒后再次执行该函数


def endless(times=0, text=''):
    global day_to_change, path_cluster, path_dst_bin, path_steamcmd, time_to_reset
    path_clu_ini = pjoin(path_cluster, 'cluster.ini')
    day_to_change_real = day_to_change - 1  # n天早上转，只等待n-1天
    reset_time = time_to_reset * 60 * 60
    change_time = day_to_change_real * 8 * 60
    day_time = 8 * 60
    t = day_time
    try:
        print(now(), '检测是否转为无尽')
        day, passed_time, season, meta_time = survival_days()
        if day == 0:
            print(now('blank'), '不转为无尽 无有效世界快照文件')
            t = change_time
            return

        act_time = active_time()
        if not act_time:
            print(now('blank'), '不转为无尽 未找到玩家快照文件')
            t = change_time
            return

        with open(path_clu_ini, 'r', encoding='utf-8') as f:
            data = f.read()
        if search(r'(\n\s*game_mode\s*=\s*)endless', data):
            print(now('blank'), f'已经是无尽 天数：{day} 季节：{season}')
            t = change_time + reset_time - (time() - act_time)  # 已经是无尽，下次检测时间就是预计重置时间延后change_time
            return

        if day <= day_to_change_real:
            #              总等待时间      -       快照记录的已过天数时间  -   创建快照到现在的时间 - 创建快照时当天已过时间 + 延迟检测时间
            t = day_time * day_to_change_real - day_time * (day - 1) - (time() - meta_time) - passed_time + 5
            t = t if t > 0 else max(day_time * (day_to_change_real - day), day_time)  # 除了前一天下线，保证指定天数后5s转模式

            text_temp = f'不转为无尽 天数：{day} 季节：{season}'
            if text_temp == text:
                times += 1
                if times == 1:
                    print(now('blank'), text_temp, '避免刷屏，此天数通知将暂时忽略')
            else:
                times = 0
                text = text_temp
                print(now('blank'), text_temp)
            return

        times = 0
        # 修改设置，改为无尽模式
        with open(path_clu_ini, 'r', encoding='utf-8') as f, open(path_clu_ini + '.temp', 'w+', encoding='utf-8') as f2:
            newdata = sub(r'(\n\s*game_mode\s*=\s*)[\d\D]+?(\n)', r'\g<1>endless\g<2>', f.read())
            f2.write(newdata)
        remove(path_clu_ini)
        rename(path_clu_ini + '.temp', path_clu_ini)

        print(now('blank'), '即将重启为无尽模式')
        send_messages('endless')  # 发送公告提示重启
        running_list = [i[0] for i in zip(world_list, running(world_list)) if i[1]]  # 记录正在运行的世界，最后开启
        stop_world(running_list)
        start_world(running_list)
        print(now('blank'), '已更改为无尽模式')
        t = change_time + reset_time - (time() - active_time())  # 已经是无尽，下次检测时间就是预计重置时间延后change_time
    except Exception as e:
        print(now('blank'), f'endless函数出错:：{e}')
    finally:
        t = max(t, 5)
        if times < 2:
            print(now('blank'), f'下次检测时间：{now(time() + t)}')
        Timer(t, endless, [times, text]).start()  # 间隔t秒后再次执行该函数


def update(tick=0, tick2=0):
    global interval_update, path_cluster, path_dst, path_dst_bin, path_steamcmd, path_steam, world_list, world_status
    # cmd_new_buildid = './steamcmd.sh +login anonymous +app_info_update 1 +app_info_print 343050 +quit | sed "1,/branches/d" | sed "1,/public/d" | grep -m 1 buildid | tr -cd [:digit:]'
    cmd_build = ['./steamcmd.sh', '+login', 'anonymous', '+app_info_update', '1', '+app_info_print', '343050', '+quit']
    # path_appinfo = pjoin(path_steam, 'appcache/appinfo.vdf')
    path_local_acf1 = pjoin(path_dst, 'steamapps', 'appmanifest_343050.acf')  # 自定义饥荒文件夹的acf位置
    path_local_acf2 = pjoin(path_steam, 'steamapps', 'appmanifest_343050.acf')  # 默认安装的acf位置
    text_normal = '过去一天中检测更新96次，无可用更新'
    text_update = f'过去一天中检测更新96次，更新{tick2}次'
    cmd_update = ['./steamcmd.sh', '+login', 'anonymous', '+force_install_dir', path_dst, '+app_update', '343050',
                  'validate', '+quit']
    time_start = time()
    try:
        if tick == 0:
            print(now(), '正在检测更新')
        elif tick == 97:
            print(now(), text_update if tick2 else text_normal)
            tick, tick2 = 1, 0

        # 获取远程buildid
        test_start = time()
        # if exists(path_appinfo):  # 删除appinfo缓存文件。据说不删会获取到缓存里的旧id，但是测试有更新时可以正常获取到新id。
        #     remove(path_appinfo)  # 删：用时~30s，不删：用时~5s
        out1, err1 = send_cmd(cmd_build, cwd=path_steamcmd, timeout=300)
        buildids_new = findall(r'"branches"[\d\D]*?"public"[\d\D]*?"buildid"\s*"(\d+)"', out1)
        if not buildids_new:
            if 'Timed out waiting for AppInfo update.' in out1:
                err1, out1 = '更新 appinfo 超时', ''
            if '(Service Unavailable)' in out1:
                err1, out1 = '服务器繁忙', ''
            err1 = '\n'.join(line for line in err1.split('\n')
                             if '): ignored.' not in line)  # 去除被忽略的错误
            out1 = '\n'.join(line for line in out1.split('\n')
                             if 'Warning: ' not in line)  # 去除警告
            print(now(), f'检测最新buildid失败，耗时：{time() - test_start}，原因：{err1}')
            print(now(), out1) if out1 else 0
            return
        newbuildid = int(buildids_new[0])

        # 获取本地buildid
        if exists(path_local_acf1):
            path_local_acf = path_local_acf1
        elif exists(path_local_acf2):
            path_local_acf = path_local_acf2
        else:
            print(now(), '检测本地buildid失败，原因：未找到本地版本文件。请重启饥荒服务器再次尝试')
            return
        with open(path_local_acf, 'r') as f:
            data_acf = f.read()
        buildid_old = search(r'(?<=\t"buildid"\t\t")\d+', data_acf)
        if not buildid_old:
            print(now(), f'检测本地buildid失败，原因：未在文件{path_local_acf}中检索到buildid。请重启饥荒服务器再次尝试')
            return
        oldbuildid = int(buildid_old.group())

        if newbuildid == oldbuildid:
            if tick == 0:
                print(now('blank'), '无可用更新')
            return
        elif newbuildid < oldbuildid:
            print(now(), '本地版本比远程版本高，可能有点问题')
            return

        print(now(), '开始更新游戏')
        tick2 += 1
        out, err = '', ''  # 报两个黄杠杠看着真难过
        for times in range(5):
            out, err = send_cmd(cmd_update, 300, cwd=path_steamcmd)
            if 'Success!' in out:
                break
            print(now('blank'), f'尝试更新失败{times + 1}次')
        else:
            print(now('blank'), '多次尝试更新失败')
            print(now('blank'), 'out:', out)
            print(now('blank'), 'err:', err)
            return

        print(now('blank'), '更新完毕')
        send_messages('update')  # 发送公告提示重启
        running_list = [i[0] for i in zip(world_list, running(world_list)) if i[1]]  # 记录正在运行的世界，最后开启
        stopped_list = [i for i in world_list if i not in running_list]
        test_start = []
        for world in stopped_list:
            if world_status.get(world, {}).get('status', [-1])[0] not in [-1, 0]:  # -1 代表不存在，0 代表正常关闭
                test_start.append(world)
                world_status[world]['is_run'][0] = 0
                world_status[world]['status'][0] = 0

        stop_world(running_list)
        write_mods_setup()
        start_world(running_list + test_start)
    except Exception as e:
        print(now('blank'), 'update函数出错')
        print(now('blank'), e)
    finally:
        tick += 1
        t = max(interval_update * 60 - (time() - time_start), 60)
        Timer(t, update, [tick, tick2]).start()  # 间隔t秒后再次执行该函数


def chatlog():
    global path, path_cluster, time_to_backupchat, master_name
    try:
        path_chatlog = pjoin(path_cluster, master_name, 'server_chat_log.txt')
        path_bakdir = pjoin(dirname(path), 'chatlog')
        time_for_path = now()
        month = time_for_path[:7]
        bakfile_raw = f'{time_for_path[8:10]}_{{}}.txt'  # 18_0.txt  {day}_{count}.txt
        path_bakdir_month = pjoin(path_bakdir, month)
        path_bakfile, path_bakfile_next = '', ''

        if not exists(path_chatlog):  # 是否存在日志文件
            return
        if not exists(path_bakdir):  # 创建chatlog文件夹
            mkdir(path_bakdir)
        if not exists(path_bakdir_month):  # 创建chatlog/month文件夹
            mkdir(path_bakdir_month)

        for count in range(10000):  # 获取当天最后一个版本的备份文件。如果当天没有备份，复制日志过来
            path_bakfile = pjoin(path_bakdir_month, bakfile_raw.format(count))
            if not exists(path_bakfile):
                copyfile(path_chatlog, path_bakfile)
                return
            path_bakfile_next = pjoin(path_bakdir_month, bakfile_raw.format(count + 1))
            if not exists(path_bakfile_next):
                break

        size_chatlog = stat(path_chatlog).st_size
        size_bakfile = stat(path_bakfile).st_size
        if size_chatlog == size_bakfile:  # 大小一样说明没有变化
            return
        elif size_chatlog < size_bakfile:  # 原文件比备份小，复制为新的备份文件
            copyfile(path_chatlog, path_bakfile_next)
            return
        elif not size_bakfile:  # 备份为空则覆盖
            copyfile(path_chatlog, path_bakfile)
            return
        with open(path_chatlog, 'rb') as f, open(path_bakfile, 'rb') as f2:
            data, data2 = f.read(500), f2.read(500)
        index = min(len(data), len(data2))
        # 文件开头一样说明还是同一份日志，直接覆盖；不一样，复制为新的备份文件
        path_bakfile = path_bakfile if data[:index] == data2[:index] else path_bakfile_next
        copyfile(path_chatlog, path_bakfile)
    except Exception as e:
        print(now(), 'chatlod函数出错')
        print(now('blank'), e)
    finally:
        t = max(time_to_backupchat * 60, 30)
        Timer(t, chatlog).start()  # 间隔t秒后再次执行该函数


def getmodinfo(mod_ids):
    global steam_api_key
    # https 偶尔会失败，http 失败几率比较低
    url_nonkey = 'http://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/'
    url_apikey = 'http://api.steampowered.com/IPublishedFileService/GetDetails/v1/'
    data = {}
    if isinstance(mod_ids, (str, int)):
        data['itemcount'] = 1
        data['publishedfileids[0]'] = mod_ids
    elif isinstance(mod_ids, (list, tuple, set, dict)):
        data['itemcount'] = num = len(mod_ids)
        for modid in mod_ids:
            data[f'publishedfileids[{(num := num - 1)}]'] = modid
    else:
        raise TypeError('传入参数类型应为以下之一：str, int, list, tuple, set, dict')

    if steam_api_key:
        data['key'] = steam_api_key
        data['language'] = 6  # 0英文，6简中，7繁中
        url = f'{url_apikey}?{urlencode(data)}'
        req = Request(url=url)
    else:
        data = urlencode(data).encode('utf-8')
        req = Request(url=url_nonkey, data=data)

    res = urlopen(req, timeout=20)
    response = res.read().decode('utf-8')
    res.close()

    results = loads(response).get('response').get('publishedfiledetails')
    mods_info_success = {}
    mods_info_fail = []
    for result in results:
        mod_id = result.get('publishedfileid')
        state = result.get('result')
        if state == 1:
            mods_info_success[mod_id] = {
                'mod_name': result.get('title'),
                'updated_time': result.get('time_updated'),
            }
        else:
            mods_info_fail.append(mod_id)

    return mods_info_success, mods_info_fail


def parse_modacf(path_acf, return_local=True):
    """通过游戏启动后定时调用steam更新的acf文件判断是否有mod更新
    在当前版本，服务器开启时会读取一次acf文件，之后调用steam更新的acf文件不会保存回去，可能是在内存中，关闭时再覆写 （仅更新mod模式应该还是原来的策略）
    就会导致 1 不能直接通过这个检测更新，2 运行期间开启额外进程更新mod后，额外进程修改的acf会被后关闭的主进程覆写，导致信息出问题
    避免第二个问题，1 更新完关闭后正常启动两次服务器，利用第一次调用steam，更新acf文件，2 更新完复制acf文件，关闭服务器后，覆写"""
    with open(path_acf, 'r', encoding='utf-8') as f:
        data = f.read()
    data_local, data_remote = data.split('WorkshopItemDetails')
    mod_version_touch = findall(r'"(\d+)"\n\t\t{[\d\D]+?"timetouched"\t\t"(\d+)"', data_remote)
    mod_version_touch = {i[0]: i[1] for i in mod_version_touch}
    if return_local:
        return mod_version_touch

    # 以下当前版本失效
    # update_code = search(r'(?<="NeedsUpdate"\t\t")\d+(?=")', data).group(0)
    # if update_code == '0':  # 游戏启动时 steam 会检测已经安装的所有mod的版本，也包括现在没有启用的mod，这种就不用管，主函数会再判断
    #     return []
    # data_local, data_remote = data.split('WorkshopItemDetails')
    # mod_version_local = findall(r'"(\d+)"\n\t\t{[\d\D]+?"timeupdated"\t\t"(\d+)"', data_local)  # \d+分别是modid和对应时间
    # mod_version_local = {i[0]: i[1] for i in mod_version_local}
    # mod_version_remote = findall(r'"(\d+)"\n\t\t{[\d\D]+?"timeupdated"\t\t"(\d+)"', data_remote)
    # mod_version_remote = {i[0]: i[1] for i in mod_version_remote}
    # need_update = []
    # for i in mod_version_local:
    #     if i in mod_version_remote:  # 两部分mod数量会不一致，虽然不清楚原因，也可能写的时候知道现在忘了。反正启用的mod肯定两个都有
    #         if mod_version_local.get(i) != mod_version_remote.get(i):
    #             need_update.append(i)
    # return need_update


def get_modlist(don_check_lack=True):
    global path_cluster, path_dst, path_dst_bin, world_list, ugc_dir
    path_ugc_clu = pjoin(path_dst, 'ugc_mods', basename(path_cluster))
    path_mods = pjoin(path_dst, 'mods')
    mod_list, mod_lack_list, mod_single, mod_lack_single = [], [], {}, {}
    try:
        for world in world_list:  # 通过modoverrides.lua文件获取开启的modid
            modo_path = pjoin(path_cluster, world, 'modoverrides.lua')
            if exists(modo_path):
                with open(modo_path, 'r', encoding='utf-8') as f:
                    data = f.read()
                data = sub(r'(?<=[^-])--\[\[[\S\s]*?]]', '', data)  # 删去多行注释
                data = sub(r'--[\S\s]*?(?=\n)', '', data)  # 删去单行注释
                # 复杂是因为一些mod会有依赖mod，这些mod要排除掉。这样应该可以保证准确率
                mod_list_single = findall(r'(?<=\["workshop-)\d+(?="]\s*=\s*{)', data.replace('\'', '"'))
                if mod_list_single:
                    mod_list.extend(mod_list_single)
                    mod_single[world] = list(set(mod_list_single))
        mod_list = list(set(mod_list))

        if don_check_lack:
            for world in world_list:  # 查找是否有mod尚未下载并提示。
                path_ugc_world = pjoin(ugc_dir.get(world, '') or pjoin(path_ugc_clu, world), 'content', '322330')
                mod_lack_single[world] = []
                for mod_id in mod_single.get(world, []):
                    path_modinfo_1 = pjoin(path_mods, 'workshop-' + mod_id, 'modinfo.lua')
                    path_modinfo_2 = pjoin(path_ugc_world, mod_id, 'modinfo.lua')
                    if exists(path_modinfo_1) or exists(path_modinfo_2):
                        continue
                    mod_lack_list.append(mod_id)
                    mod_lack_single.get(world).append(mod_id)
            if mod_lack_list:
                mod_lack_list = list(set(mod_lack_list))
                print(now('blank'), f"mod {'、'.join(mod_lack_list)} 尚未下载，已作为待更新项加入更新列表")

        # 所有世界已启用的 mod 列表 | 各个世界与对应已启用的 mod 列表的字典 | 各个世界与对应已启用但未下载的 mod 列表的字典
        return mod_list, mod_single, mod_lack_single
    except Exception as e:
        print(now(), 'get_modlist函数出错，未能找到开启的mod')
        print(now('blank'), e)
        return [], {}, {}


def write_mods_setup():
    try:
        global path_dst, path_cluster
        path_mods_setup = pjoin(path_dst, 'mods/dedicated_server_mods_setup.lua')
        mods_list = get_modlist(False)[0]
        mods_setup_text = '\n'.join([f'ServerModSetup("{i}")' for i in mods_list])
        if exists(path_mods_setup):
            with open(path_mods_setup, 'w+', encoding='utf-8') as f:
                f.write(mods_setup_text)
    except Exception as e:
        print(now(), 'write_mods_setup函数出错')
        print(now('blank'), e)


def update_mod(tick=0, tick2=0, mode=0):
    global path_cluster, path_dst, path_dst_bin, world_list, ugc_dir, interval_update_mod
    dir_clu = basename(path_cluster)
    path_ugc_clu = pjoin(path_dst, 'ugc_mods', basename(path_cluster))
    text_normal = f'今日检测mod更新{tick}次，无可用更新'
    text_update = f'今日检测mod更新{tick}次，更新{tick2}次'
    try:
        if tick == 0:
            print(now(), '正在检测mod更新')
        if mode == 1:
            print(now(), text_update if tick2 else text_normal)
            tick, tick2 = 1, 0

        mod_list, mod_single, mod_lack_single = get_modlist()  # 获取当前存档启用的 modid

        mods_version_local = {}
        for world in world_list:  # 通过 steam acf 文件获取已经下载的 modid 与更新时间
            mods_version_local[world] = []
            path_acf = pjoin(ugc_dir.get(world, '') or pjoin(path_ugc_clu, world), 'appworkshop_322330.acf')
            if exists(path_acf):
                mods_version_local[world] = parse_modacf(path_acf)
            else:
                print(now('blank'), f'未找到{world}世界 mod 信息')

        for i in range(3):
            try:
                mod_version_remote, mod_version_remote_fail = getmodinfo(mod_list)
                break
            except Exception as e:
                print(now(), '获取 mod 信息出错，原因：', end='')
                if 'HTTP Error 503: Service Unavailable' in e.__str__():
                    e = 'steam webapi 服务器繁忙'
                print(e)
        else:
            print(now(), '从 webapi 获取 mod 信息失败')
            return
        if mod_version_remote_fail:
            print(now(), f'mod: {"、".join(mod_version_remote_fail)} 无权限获取信息或 mod 不存在，请填写 steam apikey')

        need_update_dict = {}
        # 逐个世界检查：各个 mod 最后更新时间 与 acf 文件记录的 mod 上次更新时间，获取各个世界需要更新的 modid 与 mod 名
        for world, world_mods in mod_single.items():
            need_update_dict[world] = {}
            world_mods_local = mods_version_local.get(world, {})
            for mod_id, mod_info in mod_version_remote.items():
                mod_uptime = mod_info.get('updated_time')
                if int(world_mods_local.get(mod_id, 0)) < int(mod_uptime):
                    need_update_dict[world][mod_id] = mod_info.get('mod_name')

        need_update_list = {mod_id: mod_name for world_mods in need_update_dict.values() for mod_id, mod_name in world_mods.items()}

        if not need_update_list:
            if tick == 0:
                print(now('blank'), '没有mod需要更新')
            return

        need_update_name_str = '、'.join([need_update_list.get(i, '') or i for i in need_update_list])

        print(now(), '开始更新mod', need_update_name_str)
        write_mods_setup()  # 更新一下mod_setup文件，避免文件被改动过造成不自动下载mod的问题
        tick2 += 1

        start_update = [world for world, world_val in need_update_dict.items() if world_val]
        updated_mods, updated_worlds = {}, {}
        for world in start_update:
            need_update = need_update_dict.get(world)
            path_acf = pjoin(ugc_dir.get(world, '') or pjoin(path_ugc_clu, world), 'appworkshop_322330.acf')
            cmd = ['./dontstarve_dedicated_server_nullrenderer_x64', '-cluster', dir_clu, '-shard', world]
            if ugc_dir.get(world, ''):
                cmd += ['-ugc_directory', ugc_dir.get(world, '')]
            cmd += ['-only_update_server_mods']
            times = 0
            while True:
                times += 1
                out, err = send_cmd(cmd, cwd=path_dst_bin)
                if ']: FinishDownloadingServerMods Complete!' in out:

                    update_fail = []
                    mods_local = parse_modacf(path_acf)
                    for mod_id in need_update:
                        if int(mod_version_remote[mod_id].get('updated_time')) > int(mods_local.get(mod_id, 0)):
                            update_fail.append(mod_id)

                    with open(path_acf, 'r', encoding='utf-8') as f:
                        data = f.read()

                    if not update_fail:
                        updated_mods.update(need_update)
                        updated_worlds[world] = data
                        break

                    for modid in update_fail:  # 删去acf文件中更新失败的mod的信息，下次尝试更新时就会覆盖下载该mod
                        data = sub(r'\n\t\t"{}"\n\t\t{{[\d\D]+?}}'.format(modid), '', data)
                    with open(path_acf + 'tmp', 'w+', encoding='utf-8') as f:
                        f.write(data)
                    remove(path_acf)
                    rename(path_acf + 'tmp', path_acf)

                    if times > 5:
                        mods_success = {i: j for i, j in need_update.items() if i not in update_fail}
                        mods_fail = {i: j for i, j in need_update.items() if i in update_fail}
                        name_success_str = '、'.join([mods_success.get(i, '') or i for i in mods_success])
                        name_fail_str = '、'.join([mods_fail.get(i, '') or i for i in mods_fail])
                        print(now('blank'), f'世界{world}更新mod {name_success_str} 成功')
                        print(now('blank'), f'世界{world}更新mod {name_fail_str} 失败')
                        if mods_success:
                            updated_mods.update(mods_success)
                            updated_worlds[world] = data
                        break
                else:
                    print(now('blank'), f'{world}更新mod失败{times}次')
                    if times > 5:
                        print(now('blank'), f'{world}更新mod失败')
                        print(now('blank'), f'out: {out}')
                        print(now('blank'), f'err: {err}')
                        break
        if not updated_mods:
            print(now('blank'), '更新mod失败')
        updated_mods_str = '、'.join([updated_mods.get(i, '') or i for i in updated_mods])
        print(f"{'':>20}mod 更新完成。开始重启服务器")

        send_messages('update_mod', updated_mods_str)  # 发送公告提示重启
        running_list = [i[0] for i in zip(world_list, running(world_list)) if i[1]]  # 记录已经正在运行的世界，最后开启，要不要只重启已更新的
        stop_world(running_list)
        for world in updated_worlds:  # 覆写被游戏进程覆写的acf文件
            path_acf = pjoin(ugc_dir.get(world, '') or pjoin(path_ugc_clu, world), 'appworkshop_322330.acf')
            with open(path_acf + 'tmp', 'w+', encoding='utf-8') as f:
                f.write(data)
            remove(path_acf)
            rename(path_acf + 'tmp', path_acf)
        start_world(running_list)
    except Exception as e:
        print(now('blank'), 'update_mod函数出错')
        print(now('blank'), e)
    finally:
        tick += 1
        t1 = max(interval_update_mod * 60, 30)  # 常规更新的间隔时间
        #  一天秒数 - 当天自设定时间到现在的秒数(当前秒数 - 设置时间对应的世界时秒数(设定时间的秒数 - 时区带来的秒数差)) % 86400
        t2 = 86400 - (time() - (0 * 3600 - localtime().tm_gmtoff)) % 86400  # 距离设定时间的（0点）的秒数
        if t1 > t2:
            mode = 1
            t = t2
        else:
            mode = 0
            t = t1
        Timer(t, update_mod, [tick, tick2, mode]).start()  # 间隔t秒后再次执行该函数。即将到通知时间，则准备输出运行次数


def auto_restart():
    global interval_restart, path_cluster, rollback, world_list, world_status
    path_clu = dirname(path_cluster)
    cluster = basename(path_cluster)
    text_right1 = b']: c_shutdown'
    text_right2 = b']: Shutting down'
    text_wrong = b'LUA ERROR stack traceback'
    text_update_mod = b']: FinishDownloadingServerMods Complete!'
    log_name = 'server_log.txt'
    t = max(interval_restart * 60, 30)
    try:
        for world in world_list:
            path_tmp = pjoin(path_clu, world)
            tar_name = f'{world}_bak.tar.gz'
            text_restart = f'{world}进程已经重新开启，开始守护'
            text_restarted = f'{world}进程曾经重新开启，开始守护'
            text_success = f'{world}进程已在崩溃后重新启动'
            cmd_tar = ['tar', '-czf', tar_name, cluster]
            cmd_untar = ['tar', '-xzf', tar_name, '-C', path_tmp]
            path_log = pjoin(path_cluster, world, log_name)
            path_tar = pjoin(path_clu, tar_name)
            is_run_times = max(120 // t + 1, 2)  # 按默认2分钟一次，连续检测到2次为标准。防止检测时间过短导致轻易达到次数从而导致误判

            is_run = world_status.setdefault(world, {}).setdefault('is_run', [0])  # 连续多次检测到服务器运行，开启守护。防止用户手动尝试启动时误判
            status = world_status.setdefault(world, {}).setdefault('status', [0])  # 记录状态码
            if running(world):
                if status[0] != 0:
                    is_run[0] += 1
                    if is_run[0] == is_run_times:
                        print(now(), text_restart if status[0] == 9999 else text_success)
                        is_run[0], status[0] = 0, 0
                continue
            if not exists(path_log):
                is_run[0] = 0
                continue
            with open(path_log, 'rb') as f:
                if stat(path_log).st_size > 204800:  # 日志过大时只读取一部分。清理一份世界快照加六玩家快照输出信息占428字节(50+63*6)
                    f.seek(-200000, 2)
                data = f.read()
            if text_right1 in data or (text_right2 in data[-99:] and text_wrong not in data):
                if status[0] != 0:
                    is_run[0] += 1
                    if is_run[0] == is_run_times:
                        print(now(), text_restarted if status[0] == 9999 else text_success)
                        is_run[0], status[0] = 0, 0
                continue
            if text_update_mod in data[-99:]:  # 检测更新mod特征信息，以免在世界关闭情况下更新mod后被判定为崩溃
                continue  # 只检测末尾字符，避免更新完mod后世界崩溃带来的误判

            is_run[0] = 0
            if status[0] == 0:
                status[0] = 1
                print(now(), f'{world}进程因未知原因不存在，尝试启动。正在备份当前存档:{path_tar}')
                send_cmd(cmd_tar, cwd=path_clu)  # 备份存档
                if not exists(path_tar):
                    status[0] = 9999
                    print(now('blank'), '未能备份存档，可能是权限不足。若启动失败将直接暂停守护')
                start_world(world) if not running(world) else 0
            elif status[0] <= rollback:
                status[0] += 1
                print(now(), f'{world}进程启动失败，第{status[0] - 1}次尝试回档再次启动。')
                newest_path = survival_days(world)
                if not newest_path:
                    status[0] = 9999
                    print(now('blank'), '未找到快照，取消操作，暂停守护')
                    continue
                remove(newest_path)
                remove(newest_path.replace('.meta', ''))
                start_world(world) if not running(world) else 0
            elif status[0] == rollback + 1:
                status[0] = 9999
                print(now(), f'{world}进程启动失败，恢复操作前存档，暂停守护')
                mkdir(path_tmp) if not exists(path_tmp) else 0
                send_cmd(cmd_untar, cwd=path_clu)  # 释放旧存档
                rmtree(pjoin(path_cluster, world))  # 删除当前存档
                copytree(pjoin(path_tmp, cluster, world), pjoin(path_cluster, world))  # 恢复旧存档
                rmtree(path_tmp)  # 删除临时存档
    except Exception as e:
        print(now('blank'), 'auto_restart函数出错')
        print(now('blank'), e)
    finally:
        Timer(t, auto_restart).start()  # 间隔t秒后再次执行该函数


def send_messages(mode, extra='', total_time=0):
    global screen_name_master, all_interval
    all_interval_s = max(all_interval * 60, 1)
    intervals = [i * all_interval_s for i in (3 / 6, 2 / 6, 1 / 6)]
    messages = {'endless': {'text': '模式已改为无尽', 'total_time': 60},
                'update': {'text': '游戏更新完成', 'total_time': 60},
                'update_mod': {'text': 'mod更新完成', 'total_time': 60}}
    message = messages.get(mode).get('text')
    message = f'{message}\\\\n' if not extra else f'{message}\\\\n{extra}\\\\n'  # 神奇的转义
    total_time = total_time or messages.get(mode).get('total_time')
    for interval in intervals:
        msg = f'{message}󰀅服务器将于{int(all_interval_s)}s后重启，预计重启后{total_time}s可重新连接󰀅'
        cmd_message = ['screen', '-S', screen_name_master, '-X', 'stuff',
                       f'TheNet:SystemMessage("{msg}")\n']
        send_cmd(cmd_message)
        all_interval_s -= interval
        sleep(interval)


def running(worldnames):  # 检查世界是否开启，参数为str时返回数字，iter时返回列表
    # 不会添加tmux支持  http://louiszhai.github.io/2017/09/30/tmux
    # tmux has-session -t session1
    # tmux kill-session -t session1
    # tmux kill-server  # close, kill all
    # tmux ls
    # tmux new -s session1 -d cmd  # -d 指后台运行
    # tmux send -t session1 cmd Enter  # Enter/C-m 发送一个回车
    global screen_dir
    status = isinstance(worldnames, str)
    worldnames, result = [worldnames] if status else worldnames, []
    try:
        stout, _ = send_cmd(['screen', '-wipe'], 10)  # 清理无效的screen会话并获取运行中的screen会话
        if 'Socket' not in stout:  # 如果结果中没有'Socket'，认为执行命令失败
            return 1 if status else tuple(1 for _ in worldnames)
        stout = ''.join([i for i in stout.split('\n') if '(Removed)' not in i])
        stout = findall(r'\t\d+\.([\d\D]*?)\t', stout)  # 匹配出screen会话名
        for worldname in worldnames:
            result += [1] if screen_dir.get(worldname) in stout else [0]
        return result[0] if status else tuple(result)
    except Exception as e:
        print(now('blank'), f'检测游戏进程是否存在失败：{e}')
        return 1 if status else tuple(1 for _ in worldnames)


def start_world(world_names):  # str, iter
    global path_cluster, path_dst_bin, screen_dir, ugc_dir
    persistent_storage_root, conf_dir, cluster = path_cluster.rsplit('/', 2)  # 完整参数看 饥荒启动参数.txt
    world_names = [world_names] if isinstance(world_names, str) else world_names
    for world_name in world_names:
        if running(world_name):
            print(now('blank'), f'{world_name}世界已在运行，取消开启')
            continue
        cmd_start = ['screen', '-dmS', screen_dir.get(world_name), './dontstarve_dedicated_server_nullrenderer_x64',
                     '-persistent_storage_root', persistent_storage_root,
                     '-conf_dir', conf_dir, '-cluster', cluster, '-shard', world_name]
        if ugc_dir.get(world_name, ''):
            cmd_start += ['-ugc_directory', ugc_dir.get(world_name)]
        send_cmd(cmd_start, 120, path_dst_bin)
    sleep(1)
    success, fail = [], []
    for world_name in world_names:
        success.append(world_name) if running(world_name) else fail.append(world_name)
    if success:
        print(now('blank'), f"已经开启世界 {'、'.join(success)}")
    if fail:
        print(now('blank'), f"未能开启世界 {'、'.join(fail)}")


def stop_world(world_names):  # str, iter
    global screen_dir
    world_names = [world_names] if isinstance(world_names, str) else world_names
    for world_name in world_names:
        send_cmd(['screen', '-wipe'])  # 清理无效的screen会话
        cmd_stop = ['screen', '-S', screen_dir.get(world_name), '-X', 'stuff', 'c_shutdown(true)\n']
        send_cmd(cmd_stop)
    sleep(9)
    success, fail = [], []
    for world_name in world_names:
        if running(world_name):
            fail.append(world_name)
            if fail.count(world_name) > 2:
                continue
            sleep(1)
            world_names.append(world_name)
            cmd_pid = ['ps', '-ef']
            cmd_kill = ['xargs', 'kill', '-9']
            print(now('blank'), f'未能关闭世界{world_name}，尝试强行停止。')
            screen_name = f' {screen_dir.get(world_name)} '  # 前后加空格以确保不会误判。比如cave和cave1
            pid_list = [i.split()[1] for i in send_cmd(cmd_pid)[0].split('\n') if screen_name in i and 'dontstarv' in i]
            send_cmd(cmd_kill, inputs='\n'.join(pid_list))
        else:
            success.append(world_name)
            while world_name in fail:
                fail.remove(world_name)

    if success:
        print(now('blank'), f"已经关闭世界 {'、'.join(success)}")
    if fail:
        print(now('blank'), f"未能关闭世界 {'、'.join(list(set(fail)))}")


def send_cmd(cmd, timeout=120, cwd=None, inputs=None):  # cmd: list or tuple, inputs: str, cwd: path, timeout: int
    # print(now(), 'send', cmd)
    stdin = PIPE if inputs else None
    process = Popen(cmd, stdin=stdin, stdout=PIPE, stderr=PIPE, cwd=cwd, start_new_session=True,
                    universal_newlines=True)
    try:  # start_new_session 创建进程组包含打开的进程，用于超时后一并关闭。自带的kill有问题，比如kill后显示为僵尸进程，执行完毕才结束
        out, err = process.communicate(inputs, timeout=timeout)
    except TimeoutExpired:
        killpg(process.pid, SIGTERM)
        print(now(), f"执行shell命令超时：{' '.join(cmd)}")
        out, err = process.communicate()
        err = err or '执行shell命令超时'
    return out, err


def now(mode=(0.0 or 0 or '' or None)):  # 无参数返回当前格式化时间 int/float参数返回对应格式化时间 其它参数返回等长空格
    if mode is None or isinstance(mode, (int, float)):
        return strftime("%Y.%m.%d %H:%M:%S", localtime(mode))
    return f"{'':19}"


def get_paths():  # 自动检测所需路径
    global path_steam_raw, path_steamcmd_raw, path_dst_raw, path_cluster_raw
    steam_file, steam_verify_1, steam_verify_2 = 'packageinfo.vdf', 'appcache', 'config'
    steamcmd_file, steamcmd_verify_1, steamcmd_verify_2 = 'steamcmd', 'linux32', 'steamcmd.sh'
    dst_file, dst_verify_1, dst_verify_2 = 'dontstarve_dedicated_server_nullrenderer_x64', 'bin64', 'version.txt'
    cluster_file, cluster_verify_1, cluster_verify_2 = 'cluster.ini', 'cluster_token.txt', 'Agreements'

    paths_steam, paths_steamcmd, paths_dst, paths_cluster = [], [], [], []
    paths_steam.append(path_steam_raw) if path_steam_raw else 0
    paths_steamcmd.append(path_steamcmd_raw) if path_steamcmd_raw else 0
    paths_dst.append(path_dst_raw) if path_dst_raw else 0
    paths_cluster.append(path_cluster_raw) if path_cluster_raw else 0

    for rt, dirs, files in walk(expanduser('~')):
        if not path_steam_raw and steam_file in files:
            if basename(rt) == steam_verify_1:
                if exists(pjoin(dirname(rt), steam_verify_2)):
                    paths_steam.append(dirname(rt))
        if not path_steamcmd_raw and steamcmd_file in files:
            if basename(rt) == steamcmd_verify_1:
                if exists(pjoin(dirname(rt), steamcmd_verify_2)):
                    paths_steamcmd.append(dirname(rt))
        if not path_dst_raw and dst_file in files:
            if basename(rt) == dst_verify_1:
                if exists(pjoin(dirname(rt), dst_verify_2)):
                    paths_dst.append(dirname(rt))
        if not path_cluster_raw and cluster_file in files:
            if cluster_verify_1 in files:
                if exists(pjoin(dirname(dirname(rt)), cluster_verify_2)):
                    paths_cluster.append(rt)

    if not (paths_steam and paths_steamcmd and paths_dst and paths_cluster):
        print('未检测到steam文件夹') if not paths_steam else 0
        print('未检测到steamcmd文件夹') if not paths_steamcmd else 0
        print('未检测到饥荒程序文件夹') if not paths_dst else 0
        print('未检测到饥荒存档文件夹') if not paths_cluster else 0
        print('请重启饥荒服务器后再次尝试，或在自定义参数内指定路径。')
        print('结束运行')
        exit()

    path_steam_ = select_path(paths_steam, steam_file, steam_verify_1, 'steam文件夹')
    path_steamcmd_ = select_path(paths_steamcmd, steamcmd_file, steamcmd_verify_1, 'steamcmd文件夹')
    path_dst_ = select_path(paths_dst, dst_file, dst_verify_1, '饥荒程序文件夹')
    path_cluster_ = select_path(paths_cluster, cluster_file, cluster_verify_1, '饥荒存档文件夹', 1)

    return path_steam_, path_steamcmd_, path_dst_, path_cluster_


def select_path(path_list, file_name, verify, text, mode=0):
    if len(path_list) == 1:
        path_new = path_list[0]
        print(f'{text}：{path_new}')
    else:
        if mode:
            path_list.sort(key=get_cluster_time, reverse=True)
        else:
            path_list.sort(key=lambda x: stat(pjoin(x, verify, file_name)).st_mtime, reverse=True)
        path_new = path_list[0]
        path_list_str = '\n'.join(path_list)
        print(f'检测到不止一个{text}，如下：\n{path_list_str}\n已根据最后修改时间选择第一项：{path_new}')
        print(f'{text}项检测到多个路径，请清理多余文件，或在自定义参数中指定路径')
    return path_new


def get_cluster_time(path_):
    mtime = [stat(pjoin(path_, i)).st_mtime for i in listdir(path_) if isdir(pjoin(path_, i))]
    return max(mtime) if mtime else 0


def show_version():
    global path
    pattern = r'version \d\d\.\d\d\.\d\d'
    with open(path, 'r', encoding='utf-8') as f:
        data = f.read()
    v = search(pattern, data)
    print(v.group() if v else '未找到版本信息')


def gc_collect():
    gc.collect()
    Timer(24 * 60 * 60, gc_collect, []).start()


if __name__ == "__main__":
    # ---自定义参数---自定义参数---自定义参数---

    # -必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-
    # 各个世界的文件夹名与其对应的screen名，第一个为主世界。此项必须确保无误
    screen_dir = {'Master': 'DST_MASTER', 'Caves': 'DST_CAVES'}
    # 结构  {'主世界文件夹名': '主世界screen会话名', '世界二文件夹名': '世界二screen会话名', '世界三文件夹名': '世界三screen会话名', ...}

    # steam 的 apikey（网页 API 密钥），访问 https://steamcommunity.com/dev/apikey 获取。仅本地使用
    # 填写错误的密钥会导致检测 mod 更新功能失效。该项用于获取未公开 mod 的信息，用于检测 mod 更新。不填会导致无法检测小部分 mod 更新，
    steam_api_key = ''
    # apikey_search 1 成功 9 不存在 15 权限不足  | 可以获取 公开、非公开、拥有好友关系的仅好友  不能获取 隐藏、没有好友关系的仅好友
    # nonkey_search 1 成功 9 不存在 权限不足     | 可以获取 公开                          不能获取 非公开、仅好友、隐藏
    # -必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-必填区-

    # -选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-
    all_interval = 2                           # 重启服务器前发送公告的提前时间（单位/分钟）
    day_to_change = 40                         # 转为无尽的天数，到达该天数5s后将会更改（单位/游戏天）
    interval_restart = 2                       # 检测游戏是否崩溃的间隔时间（单位/分钟）
    interval_update = 15                       # 检测游戏更新的间隔时间（单位/分钟）
    interval_update_mod = 15                   # 检测 mod 更新的间隔时间（单位/分钟）
    rollback = 2                               # 崩溃后尝试回档启动时允许的回档次数（单位/次）
    time_to_reset = 24                         # 服务器无人自动重置时间（单位/小时）
    time_to_backupchat = 2                     # 备份聊天记录的间隔时间（单位/分钟）
    # -选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-选填区-

    # -没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-
    # 如果不懂什么意思，不要动下面这行。 如果自定义了 ugc_mods 路径，需要填写对应绝对路径。只需要填自定义了的世界，未定义不填或留空
    ugc_dir = {'Master': '', 'Caves': ''}
    # 结构  {'世界1文件夹名': '世界1的ugc_mods路径', '世界2文件夹名': '世界2的ugc_mods路径', ...}
    path_steam_raw = ''                        # 默认留空。需要自行指定路径时填写  如'/home/ubuntu/Steam'
    path_steamcmd_raw = ''                     # 默认留空。需要自行指定路径时填写  如'/home/ubuntu/steamcmd'
    path_dst_raw = ''                          # 默认留空。需要自行指定路径时填写  如'/home/ubuntu/dst'
    path_cluster_raw = ''                      # 默认留空。需要自行指定路径时填写  如'/home/ubuntu/.klei/DoNotStarveTogether/MyDediServer'
    # -没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-没事别填区-

    # ---自定义参数---自定义参数---自定义参数---

    world_list = tuple([*screen_dir])
    master_name, screen_name_master = world_list[0], screen_dir.get(world_list[0])
    path = abspath(getsourcefile(lambda: 0))   # 获取本文件所在目录绝对路径
    show_version()                             # 打印版本
    gc_collect()                               # 内存回收
    world_status = {}                          # 初始化世界状态
    path_steam, path_steamcmd, path_dst, path_cluster = get_paths()  # 自动检测所需路径
    path_dst_bin = pjoin(path_dst, 'bin64')

    # 以下为功能区，不要哪个删哪行
    chatlog()                                  # 自动备份聊天记录 (删除该行将不会再定时备份聊天记录
    reset()                                    # 检测是否需要重置 (删除该行将不会再检测是否需要重置
    # 无尽模式下主动重置世界并改为生存会导致自动转无尽有一定的延迟。因为无尽模式下检测间隔为：自动重置时间加自动转无尽时间
    endless()                                  # 检测是否需要转为无尽 (删除该行将不会再检测是否需要转为无尽
    update()                                   # 检测是否存在并执行更新 (删除该行将不会再检测是否存在并进行更新
    update_mod()                               # 检测是否存在并执行mod更新 (删除该行将不会再检测是否存在并进行mod更新
    auto_restart()                             # 检测到游戏崩溃后自动启动 (删除该行将不会再守护游戏进程
