CREATE TABLE consulting_trends (
                                   id SERIAL PRIMARY KEY,
                                   source VARCHAR(50) NOT NULL,
                                   title TEXT NOT NULL,
                                   summary TEXT NOT NULL,
                                   url TEXT UNIQUE NOT NULL,
                                   published_date DATE,
                                   date_fetched TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);