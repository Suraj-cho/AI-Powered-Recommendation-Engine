

from graph import draw_graph_mermaid

if __name__ == "__main__":
    mermaid_code = draw_graph_mermaid()

    with open("workflow.mmd", "w", encoding="utf-8") as file:
        file.write(mermaid_code)

    print("Workflow saved to workflow.mmd")
