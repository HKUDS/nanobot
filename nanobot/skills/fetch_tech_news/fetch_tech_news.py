import requests
import json
import re
from datetime import datetime
import sys
import os

def fetch_top_stories(limit=30):
    try:
        top_ids_url = 'https://hacker-news.firebaseio.com/v0/topstories.json'
        top_ids = requests.get(top_ids_url, timeout=10).json()[:limit]
        stories = []
        for story_id in top_ids:
            item_url = f'https://hacker-news.firebaseio.com/v0/item/{story_id}.json'
            item = requests.get(item_url, timeout=5).json()
            if item and item.get('type') == 'story' and item.get('url'):
                stories.append(item)
        return stories
    except Exception as e:
        print(f"Error fetching stories: {e}")
        return []

cs_keywords = [
    'python', 'javascript', 'java', 'rust', 'go', 'c++', 'swift', 'kotlin',
    'ai', 'ml', 'machine learning', 'llm', 'api', 'docker', 'kubernetes', 'cloud', 'aws', 'azure', 'gcp',
    'algorithm', 'data structure', 'database', 'sql', 'nosql', 'frontend', 'backend', 'devops', 'security',
    'github', 'gitlab', 'stackoverflow', 'linux', 'windows', 'macos',
    'cs', 'computer science', 'coding', 'programming', 'tutorial', 'course', 'learning'
]

def filter_cs_stories(stories):
    cs_stories = []
    print(f"Total stories fetched: {len(stories)}")
    simple_keywords = [
        'python', 'javascript', 'java', 'rust', 'go', 'c++', 'swift', 'kotlin',
        'ai', 'ml', 'machine learning', 'llm', 'gpt', 'api', 'docker', 'kubernetes', 'k8s', 'cloud', 'aws', 'azure', 'gcp',
        'algorithm', 'algorithms', 'data structure', 'data structures', 'database', 'databases', 'sql', 'nosql', 
        'frontend', 'backend', 'devops', 'security', 'cybersecurity',
        'github', 'gitlab', 'stackoverflow', 'linux', 'windows', 'macos',
        'cs', 'computer science', 'coding', 'programming', 'tutorial', 'course', 'learning', 'lean', 'ssh', 'forth', 'language'
    ]
    
    for story in stories:
        title_lower = story.get('title', '').lower()
        matched_keywords = [kw for kw in simple_keywords if kw in title_lower]
        if matched_keywords:
            print(f"MATCH: {story.get('title')} -> {matched_keywords}")
            story['score'] = story.get('score', 0)
            story['comments'] = story.get('descendants', 0)
            cs_stories.append(story)
        else:
            print(f"NO MATCH: {story.get('title')}")
    
    result = sorted(cs_stories, key=lambda x: (x.get('score', 0), x.get('descendants', 0)), reverse=True)[:10]
    print(f"Final CS stories count: {len(result)}")
    return result

def format_stories(stories):
    if not stories:
        return "No CS-relevant stories found today..."
    date = datetime.now().strftime('%Y-%m-%d')
    msg = f"📰 **Hacker News CS Digest** - {date}\n\n"
    for i, story in enumerate(stories, 1):
        title = story['title']
        score = story['score']
        comments = story['comments']
        url = story['url']
        msg += f"{i}. **[{score} pts | {comments} comments]** {title}\n"
        msg += f"   {url}\n\n"
    return msg

def send_to_discord(webhook_url, message):
    try:
        data = {"content": message}
        response = requests.post(webhook_url, json=data, timeout=10)
        response.raise_for_status()
        print("Successfully sent to Discord!")
    except Exception as e:
        print(f"Discord send error: {e}")

if __name__ == "__main__":
    webhook_url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('DISCORD_WEBHOOK')
    if not webhook_url:
        print("Usage: python3 fetch_tech_news.py 'https://discord.com/api/webhooks/YOUR_WEBHOOK'")
        sys.exit(1)
    
    print("Fetching top HN stories...")
    stories = fetch_top_stories(30)
    cs_stories = filter_cs_stories(stories)
    message = format_stories(cs_stories)
    print("Sending to Discord...")
    send_to_discord(webhook_url, message)
