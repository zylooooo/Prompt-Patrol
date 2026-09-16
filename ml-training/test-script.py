import os
from dotenv import load_dotenv
import mlflow

load_dotenv()

repo_owner = os.getenv('DAGSHUB_REPO_OWNER')
repo_name = os.getenv('DAGSHUB_REPO_NAME')

mlflow.set_tracking_uri(f'https://dagshub.com/{repo_owner}/{repo_name}.mlflow')

mlflow.set_experiment("trial-test")

with mlflow.start_run():

    mlflow.log_param("model", "roberta")

    mlflow.log_param("learning_rate", 1e-5)

    mlflow.log_metric("f1", 0.82)

    mlflow.log_metric("auc", 0.91)

    with open("notes.txt", "w") as f:
        f.write("hello dagshub")

    mlflow.log_artifact("notes.txt")

print("done")