import csv
from collections import Counter

rows = list(csv.DictReader(open(r"C:\Users\Asus\thermalguard\data\firms_seed.csv")))
jh = [r for r in rows if 23.6 <= float(r["latitude"]) <= 23.95 and 86.0 <= float(r["longitude"]) <= 86.7]
print("jharia-area csv rows:", len(jh))
print(Counter((float(r["latitude"]), float(r["longitude"])) for r in jh).most_common(12))

# check where all rows land by region membership
def reg(r):
    lat, lon = float(r["latitude"]), float(r["longitude"])
    if 23.6 <= lat <= 23.9 and 86.1 <= lon <= 86.6:
        return "jharia"
    if 22.3 <= lat <= 22.6 and 69.9 <= lon <= 70.3:
        return "jamnagar"
    if 30.2 <= lat <= 31.35 and 74.7 <= lon <= 76.8:
        return "punjab"
    if 29.95 <= lat <= 30.2 and 79.0 <= lon <= 79.35:
        return "uttarakhand"
    return "noise/other"
print(Counter(reg(r) for r in rows))