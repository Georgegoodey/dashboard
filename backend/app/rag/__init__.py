"""Retrieval for the text-to-SQL assistant, over the Postgres lettings data.

- `schema`: the text that tells the model which views and columns exist (retrieved from the live database).
- `search`: full-text search over advert wording, so questions such as "quiet flat with a garden" can find properties
  by meaning-bearing words and the model can then query them with SQL. Postgres tsvector search, not vectors.
"""
