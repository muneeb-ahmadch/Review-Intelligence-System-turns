WITH base AS (
    SELECT
        DATE(r.at_ts) AS day,
        COUNT(*) AS total_reviews,
        AVG(CAST(r.score AS DOUBLE)) AS avg_rating,
        AVG(CASE WHEN e.sentiment_label = 'negative' THEN 1.0 ELSE 0.0 END) AS pct_negative,
        AVG(CASE WHEN e.sentiment_label = 'positive' THEN 1.0 ELSE 0.0 END) AS pct_positive,
        SUM(CASE WHEN COALESCE(e.severity_score, 0.0) >= 0.80 THEN 1 ELSE 0 END) AS critical_count
    FROM reviews_raw r
    JOIN reviews_enriched e USING (review_id)
    GROUP BY 1
),
issue_rows AS (
    SELECT
        DATE(r.at_ts) AS day,
        CAST(je.value ->> 'label' AS VARCHAR) AS label,
        COALESCE(e.severity_score, 0.0) AS severity_score
    FROM reviews_raw r
    JOIN reviews_enriched e USING (review_id)
    LEFT JOIN LATERAL json_each(COALESCE(e.issues_json, '[]')) AS je ON TRUE
    WHERE CAST(je.value ->> 'label' AS VARCHAR) IS NOT NULL
),
issue_agg AS (
    SELECT
        day,
        label,
        COUNT(*) AS review_count,
        SUM(severity_score) AS weighted_severity
    FROM issue_rows
    GROUP BY 1, 2
),
issue_ranked AS (
    SELECT
        day,
        label,
        review_count,
        weighted_severity,
        ROW_NUMBER() OVER (
            PARTITION BY day
            ORDER BY weighted_severity DESC, review_count DESC, label ASC
        ) AS rn
    FROM issue_agg
),
top_issues AS (
    SELECT
        day,
        CAST(
            to_json(
                list(
                    struct_pack(
                        label := label,
                        review_count := review_count,
                        weighted_severity := ROUND(weighted_severity, 4)
                    )
                    ORDER BY weighted_severity DESC, review_count DESC, label ASC
                )
            ) AS VARCHAR
        ) AS top_issues_json
    FROM issue_ranked
    WHERE rn <= 5
    GROUP BY 1
)
SELECT
    b.day,
    b.total_reviews,
    ROUND(b.avg_rating, 4) AS avg_rating,
    ROUND(b.pct_negative, 4) AS pct_negative,
    ROUND(b.pct_positive, 4) AS pct_positive,
    b.critical_count,
    COALESCE(t.top_issues_json, '[]') AS top_issues_json,
    0 AS churn_high_users,
    '{}' AS anomaly_flags_json
FROM base b
LEFT JOIN top_issues t USING (day)
ORDER BY b.day;
