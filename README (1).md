# AI-Powered Listing Recommendation Engine

A domain-independent recommendation prototype that accepts a user's
natural-language request, searches structured listing data, and returns
relevant listings with explanations.

## Project Overview

The application is designed to work across multiple listing categories
instead of being limited to one domain. The sample SQLite database
contains 30 listings across six categories:

-   Rooms
-   Hotels
-   Jobs
-   Courses
-   Electronics
-   Cars

A user submits a request through the web interface. The FastAPI backend
invokes a LangGraph workflow that uses an LLM and database tools to
interpret the request and query the listings database.

## Key Features

-   Natural-language listing search
-   Multiple listing categories in one structured dataset
-   SQLite database for listing storage
-   FastAPI backend
-   LangGraph workflow orchestration
-   Groq-hosted LLM through LangChain's `ChatGroq`
-   SQL/schema tools for inspecting and querying data
-   Recommendation extraction and match-reason generation
-   Simple browser-based interface
-   Health endpoint for basic service checks

## Technology Stack

  Area                     Technology
  ------------------------ ---------------------------------------------
  Language                 Python
  API                      FastAPI
  Workflow orchestration   LangGraph
  LLM integration          LangChain `ChatGroq`
  LLM provider             Groq
  Database                 SQLite
  Frontend                 HTML, CSS, JavaScript (`static/index.html`)
  Listing data             Structured rows with JSON attributes

## Architecture

``` mermaid
flowchart TD
    U["User"] --> UI["Frontend<br/>static/index.html"]
    UI --> API["Main.py<br/>FastAPI"]
    API --> G["graph.py<br/>LangGraph workflow"]
    G --> LLM["Groq LLM<br/>ChatGroq"]
    G --> H["recom_agent.py<br/>Prompts and SQL helpers"]
    H --> DB[("listings.db<br/>SQLite")]
    G --> API
    API --> UI
```

### Main project files

  -----------------------------------------------------------------------
  File                                Responsibility
  ----------------------------------- -----------------------------------
  `Main.py`                           FastAPI application and API
                                      endpoints; invokes the
                                      recommendation workflow and builds
                                      the API response

  `graph.py`                          Defines the LangGraph nodes and
                                      transitions, and configures the
                                      LLM/tool workflow

  `recom_agent.py`                    Contains prompt/data helpers and
                                      read-only SQL helper functions

  `listings.db`                       SQLite database containing the
                                      sample listings

  `static/index.html`                 Browser-based user interface

  `show_workflow.py`                  Prints the LangGraph workflow as
                                      Mermaid text

  `.env`                              Local environment configuration,
                                      including the Groq API key and
                                      model name

  `requirements.txt`                  Python dependencies
  -----------------------------------------------------------------------

## LangGraph Workflow

The diagram below represents the workflow structure printed by
`draw_graph_mermaid()` in `graph.py`. Recommendation extraction runs
after the graph finishes; it is not a LangGraph node.

``` mermaid
flowchart TD
    START(["START"]) --> V["validate_input"]
    V -. "Invalid input" .-> F["format_response"]
    V -. "Valid input" .-> S["load_schema"]
    S --> A["agent<br/>LLM + SQL tools"]
    A -. "Tool call required" .-> T["tools<br/>Execute SQL / schema tool"]
    T --> A
    A -. "No more tool calls" .-> F
    F --> END(["END"])
    END --> E["extract_recommendations()"]
    E --> R["Build API response"]
```

### Workflow steps

1.  **Validate input:** Check the user's query before processing.
2.  **Load schema:** Load database schema context for the agent.
3.  **Agent:** The LLM interprets the request and decides whether a
    database tool is needed.
4.  **Tools:** Execute the requested SQL/schema tool and return its
    result to the agent.
5.  **Format response:** Prepare the workflow's final response.
6.  **Extract recommendations:** After graph execution, the API extracts
    listing records from tool results and prepares the recommendation
    response.

## Dataset

The prototype uses `listings.db`, with a `generic_listings` table
containing listing identifiers, names, categories, and JSON-encoded
attributes.

The sample dataset contains 30 listings across six categories, with five
listings per category. Attributes vary by category and can include
fields such as location, price, features, capacity, and availability.

The database is sample data for demonstrating the recommendation
workflow, not a live inventory source.

## Setup and Run

### Requirements

-   Python installed
-   A Groq API key
-   Internet access for LLM requests

Use a Python version supported by the packages in `requirements.txt`.

### 1. Create and activate a virtual environment

**Windows Command Prompt:**

``` bat
python -m venv venv
venv\Scripts\activate
```

### 2. Install dependencies

``` bat
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

``` env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-20b
```

Replace the placeholder with your own API key. Do not commit `.env` or
expose your key publicly.

### 4. Start the application

If your FastAPI object is named `app` in `Main.py`, run:

``` bat
uvicorn Main:app --reload
```

Use the startup command and application-object name defined in your code
if they differ.

Open the local URL printed by Uvicorn. If the app serves
`static/index.html` at the root path, open that root URL in your
browser. FastAPI's interactive API documentation is commonly available
at `/docs`.

## Example Request

Example natural-language query:

> Find available rooms in Pune with Wi-Fi under 10000 per month.

The application should interpret the request, search listing data, and
return relevant results with reasons. Actual results depend on the
database contents, query interpretation, and current implementation.

Other example queries:

-   Find an available laptop under ₹50,000 with at least 8 GB RAM.
-   Find data-related jobs in Pune.
-   Find a hotel with Wi-Fi within my budget.
-   Recommend a beginner-friendly Python course.

These are example prompts, not guarantees that every field or constraint
is currently supported.

## API

The application includes a recommendation endpoint and a health
endpoint. Confirm exact HTTP methods, request schemas, and response
fields from `Main.py`.

-   `/recommend` --- recommendation request endpoint.
-   `/health` --- basic service health check.

## Viewing the Workflow Diagram

Run the helper script to print the Mermaid source:

``` bat
python show_workflow.py
```

To view it visually, save the returned Mermaid text to a `.mmd` file and
open it with a Mermaid preview extension in VS Code. Alternatively, use
the Markdown preview for the Mermaid diagrams embedded in this README.

## Assumptions and Limitations

-   Listings are sample data, not live inventory.
-   Recommendation quality depends on the LLM's interpretation, SQL tool
    behavior, and the stored attributes.
-   Text differences such as `Wi-Fi` versus `wifi` can affect
    exact-match filters if values are not normalized.
-   SQL results should be validated against the user's hard constraints
    before being returned.
-   This prototype is not a production-ready booking, purchasing, or
    job-application system.
-   Supported attributes and behavior should be verified against the
    final code and tests.

## Future Improvements

-   Add automated tests for constraints, ranking, missing information,
    and no-match cases.
-   Validate extracted listings against the user's hard constraints.
-   Normalize feature values and category-specific attributes.
-   Add explicit ranking/scoring logic and consistent explanations.
-   Improve error handling for LLM/API failures, timeouts, and rate
    limits.
-   Expand the dataset and evaluate recommendation quality across all
    categories.

## Security Notes

-   Keep `.env` out of version control.
-   Prefer read-only database access for recommendation queries.
-   Validate SQL operations and restrict permitted query types.
-   Do not expose credentials or sensitive configuration in API
    responses.

## License

Add the license appropriate for your project before publishing or
distributing the repository.
