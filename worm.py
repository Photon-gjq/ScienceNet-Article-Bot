import requests
import json
import asyncio
from bs4 import BeautifulSoup
import os
from telegram import Bot

DATA_FILE = 'previous_articles.json'

def fetch_latest_articles():
    # 指定要抓取的網頁 URL
    url = "https://blog.sciencenet.cn/blog.php?mod=type&type=7"
    
    # 發送 HTTP GET 請求獲取網頁內容
    response = requests.get(url)

    # 檢查請求是否成功
    if response.status_code != 200:
        print(f"Failed to fetch page, status code: {response.status_code}")
        return []

    # 使用 BeautifulSoup 解析網頁 HTML
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 用於存儲文章信息的列表
    articles = []

    # 查找網頁中包含文章信息的表格
    table = soup.find('table')  # 假設文章在一個表格中
    if not table:
        print("No table found on the page.")
        return articles

    # 獲取表格中的所有行，跳過第一行（表頭）
    rows = table.find_all('tr')[1:]

    # 遍歷每一行，提取文章的詳細信息
    for row in rows:
        # 獲取行中的所有單元格
        cols = row.find_all('td')
        
        # 確保單元格數量符合預期
        if len(cols) < 6:
            continue

        # 提取每個單元格的文字內容並去除多餘的空白
        article_id = cols[0].text.strip()
        title = cols[1].text.strip()
        author = cols[2].text.strip()
        views = cols[3].text.strip()
        comments = cols[4].text.strip()
        date = cols[5].text.strip()

        # 假設鏈接在第二列的 <a> 標籤中
        link_tag = cols[1].find('a', href=True)
        link = f"https://blog.sciencenet.cn/{link_tag['href']}" if link_tag else 'No link available'

        # 將提取的信息添加到文章列表
        articles.append({
            'id': article_id,
            'title': title,
            'author': author,
            'views': views,
            'comments': comments,
            'date': date,
            'link': link
        })

    # 返回包含所有文章信息的列表
    return articles

async def send_telegram_message(articles):
    bot_token = os.getenv('BOT_TOKEN')
    chat_id = os.getenv('CHAT_ID')
    
    bot = Bot(token=bot_token)
    for article in articles:
        message = f"New Article: {article['title']}\nAuthor: {article['author']}\nLink: {article['link']}"
        try:
            await bot.send_message(chat_id=chat_id, text=message)
            print(f"Message sent: {message}")
        except Exception as e:
            print(f"Failed to send message: {e}")

def load_previous_articles():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as file:
            return set(json.load(file))
    return set()

def save_current_articles(articles):
    with open(DATA_FILE, 'w') as file:
        json.dump([article['id'] for article in articles], file)

def get_new_articles(current_articles, previous_article_ids):
    return [article for article in current_articles if article['id'] not in previous_article_ids]

if __name__ == "__main__":
    current_articles = fetch_latest_articles()
    previous_article_ids = load_previous_articles()

    new_articles = get_new_articles(current_articles, previous_article_ids)
    
    if new_articles:
        print(f"Found {len(new_articles)} new articles.")
        asyncio.run(send_telegram_message(new_articles))
        save_current_articles(current_articles)
    else:
        print("No new articles found.")