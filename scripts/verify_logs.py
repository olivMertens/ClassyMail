import os
from datetime import timedelta
from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus
from dotenv import load_dotenv

# Load env including the new LOG_ANALYTICS_WORKSPACE_ID
load_dotenv("secrets.env")

def verify():
    workspace_id = os.getenv("LOG_ANALYTICS_WORKSPACE_ID")
    if not workspace_id:
        print("Error: LOG_ANALYTICS_WORKSPACE_ID not found in env.")
        return

    print(f"Querying Workspace: {workspace_id}")
    print("Authenticating...")
    credential = DefaultAzureCredential()
    client = LogsQueryClient(credential)

    # Query for Traces (Info) and Exceptions (Error)
    query = """
    union AppTraces, AppExceptions
    | where TimeGenerated > ago(24h)
    | project TimeGenerated, Message, SeverityLevel, Type, OuterMessage
    | order by TimeGenerated desc
    | take 15
    """

    print("Sending query to Azure Monitor...")
    try:
        response = client.query_workspace(
            workspace_id=workspace_id,
            query=query,
            timespan=timedelta(hours=24)
        )

        if response.status == LogsQueryStatus.FAILURE:
            print("Query Failed!")
            print(response.partial_error)
        else:
            table = response.tables[0]
            print(f"✅ Success! Found {len(table.rows)} logs in last 24h.\n")

            for row in table.rows:
                # Project order: TimeGenerated, Message, SeverityLevel, Type, OuterMessage
                # Row is a list of values
                ts = row[0]
                msg = row[1] or row[4] # Message or OuterMessage
                lvl = row[2]
                typ = row[3]

                print(f"[{ts}] {typ} (Lvl {lvl}): {msg}")

    except Exception as e:
        print(f"❌ Error querying logs: {e}")

if __name__ == "__main__":
    verify()
