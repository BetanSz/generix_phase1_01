import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from pathlib import Path
import textwrap
import json
import sys

from clients import cosmos_digitaliezd, cosmos_table
from gpt_prompt import *
import json, ast, re
import pandas as pd
import numpy as np

items = cosmos_table.read_all_items(max_item_count=100)
df_list = []
for i, doc in enumerate(items, start=1):
    print(i, doc["id"]) #, doc.get("blob_path")
    df = pd.DataFrame(doc["rows"])
    df["id"] = doc["id"]
    df_list.append(df)
result_df = pd.concat(df_list)

embed()
cols2save = [col for col in df.columns if "evidence" not in col]
result_df[cols2save].to_markdown("result_all.md", index=False)