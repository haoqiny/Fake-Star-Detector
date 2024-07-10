import pandas as pd
import pymongo
import yaml

with open("secrets.yaml", "r") as f:
    SECRETS = yaml.safe_load(f)
client = pymongo.MongoClient(SECRETS["mongo_url"])
stars_db = client.fake_stars.stars
downloads_db = client.fake_stars.downloads

obvious_repos = pd.read_csv("data/fake_stars_obvious_repos.csv")
filtered_repos = obvious_repos[
    (obvious_repos["fake_percentage"] >= 2) | (obvious_repos["fake_stars"] >= 100)
]

unique_githubs = set(filtered_repos["github"].unique())

query = {"github": {"$in": list(unique_githubs)}}

download = list(
    downloads_db.find(query, {"github": 1, "month": 1, "downloads": 1, "_id": 0})
)
df_download = pd.DataFrame(download).groupby(["github", "month"], as_index=False).sum()
df_download.to_csv("data/filtered_repos_downloads.csv", index=False)
