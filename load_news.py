from data_ingestion.soft.news_client import NewsClient
client = NewsClient()
client.run_all_sports()
print("News loaded!")