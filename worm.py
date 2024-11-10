import requests
import json
import asyncio
from bs4 import BeautifulSoup
import os
from telegram import Bot

DATA_FILE = 'previous_articles.json'

def fetch_latest_articles():
    urls = [
        ("https://blog.sciencenet.cn/blog.php?mod=type&type=7", "科普集錦"),
        ("https://blog.sciencenet.cn/blog.php?mod=type&type=3", "觀點評述")
    ]
    
    articles = []
    
    for url, label in urls:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Failed to fetch page from {url}, status code: {response.status_code}")
            continue
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        table = soup.find('table')  # 假设文章在一个表格中
        if not table:
            print("No table found on the page.")
            continue
        
        rows = table.find_all('tr')[1:]  # 跳过表头
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 6:
                continue
            
            article_id = cols[0].text.strip()
            title = cols[1].text.strip()
            author = cols[2].text.strip()
            views = cols[3].text.strip()
            comments = cols[4].text.strip()
            date = cols[5].text.strip()
            
            link_tag = cols[1].find('a', href=True)
            link = f"https://blog.sciencenet.cn/{link_tag['href']}" if link_tag else 'No link available'
            
            articles.append({
                'id': article_id,
                'title': title,
                'author': author,
                'views': views,
                'comments': comments,
                'date': date,
                'link': link,
                'label': label
            })
    
    return articles

async def send_telegram_message(articles):
    bot_token = os.getenv('BOT_TOKEN')
    chat_id = os.getenv('CHAT_ID')
    
    bot = Bot(token=bot_token)
    for article in articles:
        message = f"新文章: {article['title']}\n作者: {article['author']}\n分類: {article['label']}\n鏈結: {article['link']}"
        try:
            await bot.send_message(chat_id=chat_id, text=message)
            print(f"Message sent: {message}")
        except Exception as e:
            print(f"Failed to send message: {e}")

def load_previous_articles():
    if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
        with open(DATA_FILE, 'r') as file:
            return set(json.load(file))
    return set()

def save_current_articles(previous_ids, new_articles):
    # 合并旧的和新的文章 ID
    updated_ids = previous_ids.union({article['id'] for article in new_articles})
    
    with open(DATA_FILE, 'w') as file:
        json.dump(list(updated_ids), file)

def get_new_articles(current_articles, previous_article_ids):
    return [article for article in current_articles if article['id'] not in previous_article_ids]

#主程序入口
if __name__ == "__main__":
    current_articles = fetch_latest_articles()
    previous_article_ids = load_previous_articles()

    new_articles = get_new_articles(current_articles, previous_article_ids)
    
    if new_articles:
        print(f"Found {len(new_articles)} new articles.")
        asyncio.run(send_telegram_message(new_articles))
        save_current_articles(previous_article_ids, new_articles)  # 传入两个参数
    else:
        print("No new articles found.")

# if __name__ == "__main__":
#     current_articles = fetch_latest_articles()

#     if current_articles:
#         print(f"Found {len(current_articles)} articles.")
#         asyncio.run(send_telegram_message(current_articles))
#         save_current_articles(current_articles)  # 更新存储的文章列表
#     else:
#         print("No articles found.")