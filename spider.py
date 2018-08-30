import requests
import json
import re
import os
import pymongo
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from requests.exceptions import RequestException
from hashlib import md5
from config import *
from multiprocessing import Pool
from json.decoder import JSONDecodeError

client = pymongo.MongoClient(MONGO_URL, connect=False)
db = client[MONGO_DB] # 其中MONGO_DB，MONGO_URL为配置文件中的参数

def get_page_index(offset, keyword):
	"""抓取索引页的内容"""
	data = { # 请求参数，offset和keyword我们设置成变量，方便改变。
		'offset': offset,
		'format': 'json',
		'keyword': keyword,
		'autoload': 'true',
		'count': '20',
		'cur_tab': 3,
		'from': 'gallery'
	}
	# urlencode()可以把字典对象转化为url的请求参数
	url = 'https://www.toutiao.com/search_content/?' + urlencode(data)
	try: # 防止程序中断
		response = requests.get(url)
		if response.status_code == 200: # 如果访问成功则返回文本内容
			return response.text
		return None
	except RequestException:
		print('请求索引页出错!' ,url)
		return None

def parse_page_index(html):
	try:
		""" 解析索引数据"""
		# json.loads()对JSON数据进行解码,转换成一个字典
		data = json.loads(html)
		# 当data这个字典存在且'data'键名存在与data字典中。data.keys()返回data这个字典所有的键名
		if data and 'data' in data.keys():
			# get() 函数返回字典中指定键的值，在这里遍历data字典中键名为'data'的
	        # 值，每个元素分别为一个图集。
			for item in data.get('data'):
				# 对于'data'的值中的每个元素，建立一个生成器，得到每个网址
				yield item.get('article_url') # 'article_url'中信息是每个图集的网址
	except JSONDecodeError:
		pass

def get_page_detail(url):
	""" 拿到详情页图的信息"""
	try:
		# 此处不加headers会导致访问详情页失败
		headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36'}
		response = requests.get(url, headers=headers)
		if response.status_code == 200:
			return response.text
		return None
	except RequestException:
		print('请求详情页出错!' ,url)
		return None

def parse_page_detail(html, url):
	""" 解析详情页"""
	soup = BeautifulSoup(html, 'lxml')
	# 通过传入css选择器，选择第一个<title>标签，获取文本内容，就是图集的标题。
	title = soup.select('title')[0].get_text()
	# 声明一个正则表达式对象，来匹配我们想要的Json语句。注意re.S使 . 能匹配任意字符。
	images_pattern = re.compile('gallery: JSON.parse\("(.*?)"\),',re.S)
	result = re.search(images_pattern, html)
	# 注意：这里的Json语句包含转义字符 \ ，不去掉会报错
	result = result.group(1).replace('\\', '')
	if result:
		data = json.loads(result) # 把Json转换为字典
		if data and 'sub_images' in data.keys():
			# 'sub_images'这个键的值是一个列表，里面每个元素是字典，包含每个图集的地址。
			sub_images = data.get('sub_images')
			images = [item.get('url') for item in sub_images] # 构造一个图集列表，包含每个图片的地址。
			for image in images:
				download_image(image) # 下载每张图片
			return { # 返回一个字典，格式化数据，准备存入MongoDB
				'title': title,
				'url': url,
				'images': images
			}

def save_to_mongo(result):
	"""存储文件到数据库"""
	if db[MONGO_TABLE].insert_one(result):
		print('已成功存储到MongoDB数据库...')
		return True
	return False

def download_image(url): # 传入的是每张图片的地址
	""" 下载图片"""
	print('正在下载...',url) # 调试信息
	try:
		# 此处不加headers会导致访问详情页失败
		headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36'}
		response = requests.get(url, headers=headers)
		if response.status_code == 200:
			save_image(response.content) # 保存图片，content返回二进制内容（当保存图片视频时）
		return None
	except RequestException:
		print('请求图片出错!' ,url)
		return None

def save_image(content):
	"""存图片"""
	# 定义文件路径，文件名把图片信息md5加密，保证每个文件名不同。
	file_path = '{0}/{1}.{2}'.format(os.getcwd() + '\images',md5(content).hexdigest(), 'jpg')
	if not os.path.exists(file_path):
		with open(file_path, 'wb') as f:
			f.write(content)
			f.close()

def main(offset):
	html = get_page_index(offset, KEYWORD)
	for url in parse_page_index(html):
		html = get_page_detail(url)
		if html:
			result = parse_page_detail(html, url)
			if result:
				save_to_mongo(result)


if __name__ == '__main__':
	groups = [x * 20 for x in range(GROUP_START, GROUP_END + 1)] # 生成一个offset列表
	pool = Pool() # 声明一个进程池
	pool.map(main, groups)
	pool.close()
	pool.join()