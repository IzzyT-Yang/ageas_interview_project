You have been provided with 3 csv files, (cutomer.csv, policy.csv, events.csv) which contain customer data, policy information and certain events that take place at an insurance company Insure4All . There are multiple brands, insurance types, and events.  We’re creating data products for event data based on ingesting csv files, which the business wants to use to be able to perform analytics /modelling etc.

You need to create a pipeline that would ingest this data and create final data products/tables. The pipeline should perform data validation checks and should be able to ingest further csv files in the future.  You can use either SQL or Python to perform this task. Along with the code, a short presentation which answers the following questions should also be submitted, and the candidate is expected to walk through this in the interview. 

Explain what sort of data checks/testing/validation you would perform and assumptions you would make including, what the final data product/s would look like and what information they would contain

- Can you describe the characteristics of the data products/tables you have created?
- Using the final data products can you create a view/report of monthly sales per brand per type?
- Can you create a view/report of claims per region ?
- The retention team is interested in a monthly report that shows overall retention rate for customers, i.e. how many have renewed versus how many have cancelled their policy, per brand  per product type. What assumptions will you make in generating this report
- We realised that some data was missing from the original ingestion and 3 additional csv files have been provided to you (customer_additional.csv,policy_additional.csv,events_additional.csv). Can you add these to your pipeline and rerun the reports?

