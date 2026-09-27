
[Role]

You are an Analytics Enginner working on a demo project according to `./docs/instructions.md`.

[Task]

Based on existing data, generate a `instructions_decomp.md` file in `./docs` according to `./docs/instructions.md`. The result file should include the detailed structure of the project and all key assumptions.

Don't touch any other files in the project.

[Project Structure]

- A postgresql database with docker-compose.yml.
- An loading/ingestion layer (Python script) that copies a customizable list of raw data directly to the raw layer of the database. 
    - The source files are in `./data` folder. The target tables are raw_customer, raw_event, and raw_policy. When adding new tables, 
    - The final tables should have original columns of the corresponding csv files + two new columns: loaded_at (timestamp) & source_file (string). All the columns in csv should be read as string.
- A dbt sub-folder (`2_transform/`) that does all the transformation and testing
    - dbt models have three layers: 
        - raw_ (source): directly holdes the raw data, 
        - stg_: deals with data cleaning; one-to-one with raw_ layer tables. Cleaning processes that should be done here: deduplication (e.g. if customer.csv and customer_additional.csv have the same customer IDs, apply the merge logic in this layer), column type casting (e.g. age should be int instead of string)
        - marts_: serves final business requests in docs/instructions.md, including: 
            - monthly sales per brand per type
            - claims per region
            - overall retention rate for customers per brand per product type
    - in the models.yml files, there should be descriptions for each model and column, as well as the proper tests. The testing strategy for each layer is:
        - raw_: all the value columns are non-negative; all the important columns are not-null
        - stg_: unique and not null for the PK columns; not null for all the important columns; accepted_range and regex tests wherever appropriate
        - marts_: unique and not null for the PK columns; row count comparison against upstream models; contracts that make sure the structure and column types of the final tables are consistent

[Important Notes]

If there are any questions, ask directly before writing them down.

If there are any assumptions that need to be made, raise them explicitly and provide initial assumptions in the result file.





- 