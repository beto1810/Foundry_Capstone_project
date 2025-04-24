import pandas as pd
from faker import Faker

# Load your file
df = pd.read_csv("Tb disease symptoms.csv")

# Initialize Faker
fake = Faker()

# Replace "Name" column with random full names
df["name"] = [fake.name() for _ in range(len(df))]

# Save to a new file
df.to_csv("updated_with_full_names.csv", index=False)

print("Done! File saved as updated_with_full_names.csv")