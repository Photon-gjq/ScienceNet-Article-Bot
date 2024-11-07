import requests
from bs4 import BeautifulSoup

import os
from telegram import Bot

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

        # 將提取的信息添加到文章列表
        articles.append({
            'id': article_id,
            'title': title,
            'author': author,
            'views': views,
            'comments': comments,
            'date': date
        })

    # 返回包含所有文章信息的列表
    return articles

# 主程序入口
if __name__ == "__main__":
    # 獲取最新的文章信息
    articles = fetch_latest_articles()
    
    # 檢查是否有文章，如果有則逐一打印
    if articles:
        for article in articles:
            print(f"ID: {article['id']}, Title: {article['title']}, Author: {article['author']}, "
                  f"Views: {article['views']}, Comments: {article['comments']}, Date: {article['date']}")
    else:
        print("No articles found.")