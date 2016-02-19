__author__ = 'Toby'

from pyquery import PyQuery as pq  # pyquery
import pycurl  # curl
from io import BytesIO  # 字节处理
import sqlite3  # 数据库
import itertools
import threading


# curl获取网页源码
def curlGetHTML(url):
    try:
        buffer = BytesIO()

        c = pycurl.Curl()
        c.setopt(c.URL, url)
        c.setopt(c.WRITEDATA, buffer)
        c.setopt(c.CONNECTTIMEOUT, 60)
        c.setopt(c.TIMEOUT, 60)
        c.setopt(c.COOKIE, 'REMOVE_ACT_ALERT=1')  # 防止跳入首页
        # c.setopt(c.PROXY, 'http://inthemiddle.com:8080')
        c.perform()

        buffer_data = buffer.getvalue()
        buffer.close()

        html = buffer_data.decode('utf-8')
        # html = buffer_data.decode()
        return html

    except Exception as e:
        print(e)
        return False


def eachRest(i, val):
    each_rest_html = val
    each_rest_pq = pq(each_rest_html)

    is_outof_sale = each_rest_pq('div.content div.outof-sale').html()  # 是否休息中
    if is_outof_sale == None:
        rest = {}
        rest['link'] = 'http://waimai.meituan.com' + each_rest_pq('a.rest-atag').attr('href').strip()  # 餐厅链接

        try:
            html = curlGetHTML(rest['link'])
            restInner(rest, html)
        except Exception as e:
            print(e)

def restInner(rest, html):
    global cur, con

    each_rest_inner_html = html
    each_rest_inner_pq = pq(each_rest_inner_html)

    rest['name'] = each_rest_inner_pq('div.shopping-cart').attr('data-poiname').strip()  # 店铺名称
    rest['delivery_min_fee'] = each_rest_inner_pq('div.widgets div.widget.discount p.delivery-min-fee').text()  # 起送价
    if rest['delivery_min_fee'].rfind('元') != -1:
        rest['delivery_min_fee'] = float(rest['delivery_min_fee'][
                                         rest['delivery_min_fee'].rfind('：') + 1:rest['delivery_min_fee'].rfind(
                                             '元')].replace(',', '').strip())
    else:
        rest['delivery_min_fee'] = 0
    rest['delivery_fee'] = each_rest_inner_pq('div.widgets div.widget.discount p.delivery-fee').text()  # 配送费
    if rest['delivery_fee'].rfind('元') != -1:
        rest['delivery_fee'] = float(
            rest['delivery_fee'][rest['delivery_fee'].rfind('：') + 1:rest['delivery_fee'].rfind('元')].replace(',',
                                                                                                              '').strip())
    else:
        rest['delivery_fee'] = 0

    print('正在获取店铺:' + rest['name'] + ' ' + rest['link'])  # log

    cur.execute('INSERT INTO rest (name, link, delivery_min_fee, delivery_fee) VALUES (?, ?, ?, ?)',
                (rest['name'], rest['link'], rest['delivery_min_fee'], rest['delivery_fee']))
    con.commit()
    rest['rid'] = cur.lastrowid

    rest_manjian = each_rest_inner_pq('div.widgets div.widget.discount i.icon.i-minus').next(
        'span.discount-desc').text()  # 边栏 满减
    if len(rest_manjian) > 0:
        for manjian in rest_manjian.split(';'):
            man = manjian[manjian.find('满') + 1:manjian.find('元')]
            jian = manjian[manjian.rfind('减') + 1:manjian.rfind('元')]

            cur.execute('INSERT INTO rest_manjian (rid, man, jian) VALUES (?, ?, ?)', (rest['rid'], man, jian))
            con.commit()

    each_rest_inner_pq('div.food-list div.pic-food').each(lambda i, val: eachRestFood(rest, i, val))


def eachRestFood(rest, i, val):
    each_food_html = val
    each_food_pq = pq(each_food_html)

    is_outof_sale = each_food_pq('div.labels span.tip').html()  # 是否无货，休息中
    if is_outof_sale == None:
        food = {}
        food['name'] = each_food_pq('div.np span.name').attr('title').strip()  # 菜名
        food['price'] = each_food_pq('div.labels div.price div.only').text()  # 菜价
        if food['price'].find('¥') != -1:
            food['price'] = float(
                food['price'][food['price'].find('¥') + 1:food['price'].find('/')].replace(',', '').strip())
        else:
            food['price'] = 0

        if food['price'] > 0.01:    # 排除垃圾
            cur.execute('INSERT INTO food (rid, name, price) VALUES (?, ?, ?)', (rest['rid'], food['name'], food['price']))
            con.commit()

def calcRest(mutex, rest, money, has_redpack, redpack, manjian_arr, food_arr):
    global plan_arr

    print('正在计算店铺: ' + rest[1])

    for i in range(1, len(food_arr)+1):
        for plan in itertools.combinations(food_arr, i):

            # 计算价格 start
            grand_amount = 0
            total_amount = 0
            for food in plan:
                grand_amount += food[3]  # price
            total_amount = grand_amount

            # 判断金额
            if grand_amount < rest[3]:  # delivery_min_fee
                continue    # 这个菜单价格低于最低配送金额

            # 粗略判断金额: 使用 grand_amount - 店铺最大满减 - 红包 + 运费 > 使用金额, 舍弃
            if manjian_arr == None or len(manjian_arr) == 0:
                if grand_amount - redpack['price'] + rest[4] > money:
                    continue
            else:
                if grand_amount - manjian_arr[0][1] - redpack['price'] + rest[4] > money:
                    continue

            # 计算满减
            if manjian_arr != None:
                for manjian in manjian_arr:
                    if grand_amount >= manjian[1]:  #  man
                        total_amount = total_amount - manjian[2]   # jian
                        break

            # 应用红包
            is_use_redpack = False
            if has_redpack and grand_amount >= redpack['min_use']:
                total_amount = total_amount - redpack['price']
                is_use_redpack = True

            # 计算运费
            total_amount += rest[4]   # deliver_fee

            if total_amount > money:
                continue   # 这个菜单的价格大于预算
            if total_amount <= money - 5:
                continue   # 这个菜单的价格小于预算，但太小，被忽略

            # 计算价格 end

            # 判断菜品 start
            # 判断粥
            zhou = 0
            for food in plan:
                if '粥' in food[2]:
                    zhou += 1
                if zhou > 1:
                    break
            if zhou > 1:
                continue  # 这个菜单里粥太多了，舍弃

            # 判断饭
            fan = 0
            for food in plan:
                if '饭' in food[2]:
                    fan += 1
                if fan > 1:
                    break
            if fan > 1:
                continue # 这个菜单饭太多了，舍弃
            # 判断菜品 end

            # 添加菜单
            if is_use_redpack:
                is_use_redpack = '是'
            else:
                is_use_redpack = '否'
            final_plan = {
                'rest': rest[1],
                'link': rest[2],
                'plan': plan,
                'is_use_redpack': is_use_redpack,
                'total_amount': total_amount
            }

            plan_arr.append(final_plan)


            if mutex.acquire(1):
                print('')
                print('====== 成功生成菜单 ======')
                print('餐厅:', final_plan['rest'])
                print('链接:', final_plan['link'])
                for f in final_plan['plan']:
                    print(f[2], '-', f[3], '元')
                print('是否使用红包:', final_plan['is_use_redpack'])
                print('合计:', final_plan['total_amount'], '元')

                mutex.release()



def doCalc(money, redpack):
    global cur, con

    mutex = threading.Lock()

    if redpack['price'] == 0 and redpack['min_use'] == 0:
        # 没有红包
        has_redpack = False
    else:
        has_redpack = True

    cur.execute('SELECT * FROM rest')
    for rest in cur.fetchall():
        cur.execute('SELECT * FROM rest_manjian WHERE rid = ? ORDER BY man DESC', (rest[0], ))   # rid
        manjian_arr = cur.fetchall()

        cur.execute('SELECT * FROM food WHERE rid = ?', (rest[0], ))
        food_arr = cur.fetchall()
        t = threading.Thread(target=calcRest, args=(mutex, rest, money, has_redpack, redpack, manjian_arr, food_arr))
        t.setDaemon(True)
        t.start()


if __name__ == '__main__':
    url = input('输入本次订餐地区列表页网址(例: http://waimai.meituan.com/home/wqj6x9t9310r):')

    money = float(input('输入本次订餐预算:'))

    if input('是否使用红包? (y/n):') == 'y':
        redpack = {}
        redpack['price'] = float(input('红包金额:'))
        redpack['min_use'] = float(input('红包的最低使用金额:'))

        if redpack['min_use'] > money:
            print('输入的消费金额小于红包最低使用限额, 红包不可用!')
            redpack['price'] = float(0)
            redpack['min_use'] = float(0)
    else:
        redpack = {}
        redpack['price'] = float(0)
        redpack['min_use'] = float(0)


    print('初始化中。。。')

    global cur, con, plan_arr
    plan_arr = []
    con = sqlite3.connect('./db.sqlite')
    cur = con.cursor()

    cur.execute('DELETE FROM rest;')
    cur.execute('VACUUM;')
    cur.execute('DELETE FROM food;')
    cur.execute('VACUUM;')
    cur.execute('DELETE FROM rest_manjian;')
    cur.execute('VACUUM;')
    cur.execute('UPDATE sqlite_sequence SET seq = "0" WHERE name = "rest";')
    cur.execute('UPDATE sqlite_sequence SET seq = "0" WHERE name = "food";')
    con.commit()



    print('')
    print('============')
    print('开始获取店铺。。。')

    rest_list_html = curlGetHTML(url)
    rest_list_pq = pq(rest_list_html)
    rest_list_pq('div.rest-list ul.list li.rest-li').each(eachRest)



    print('')
    print('============')
    print('开始计算。。。')

    doCalc(money, redpack)

    cur.close()
    con.close()
