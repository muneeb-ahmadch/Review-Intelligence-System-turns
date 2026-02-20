WITH base AS (
    SELECT
        r.app_version,
        MIN(DATE(r.at_ts)) AS first_seen_day,
        MAX(DATE(r.at_ts)) AS last_seen_day,
        COUNT(*) AS total_reviews,
        AVG(CAST(r.score AS DOUBLE)) AS avg_rating,
        AVG(CASE WHEN e.sentiment_label = 'negative' THEN 1.0 ELSE 0.0 END) AS pct_negative,
        SUM(CASE WHEN COALESCE(e.severity_score, 0.0) >= 0.80 THEN 1 ELSE 0 END) AS critical_count
    FROM reviews_raw r
    JOIN reviews_enriched e USING (review_id)
    GROUP BY 1
),
issue_rows AS (
    SELECT
        r.app_version,
        CAST(je.value ->> 'label' AS VARCHAR) AS label,
        COALESCE(e.severity_score, 0.0) AS severity_score
    FROM reviews_raw r
    JOIN reviews_enriched e USING (review_id)
    LEFT JOIN LATERAL json_each(COALESCE(e.issues_json, '[]')) AS je ON TRUE
    WHERE CAST(je.value ->> 'label' AS VARCHAR) IS NOT NULL
),
issue_agg AS (
    SELECT
        ir.app_version,
        ir.label,
        COUNT(*) AS review_count,
        SUM(ir.severity_score) AS weighted_severity
    FROM issue_rows ir
    GROUP BY 1, 2
),
issue_json AS (
    SELECT
        ia.app_version,
        CAST(
            to_json(
                list(
                    struct_pack(
                        label := ia.label,
                        review_count := ia.review_count,
                        pct_reviews := ROUND(ia.review_count::DOUBLE / NULLIF(b.total_reviews, 0), 4),
                        weighted_severity := ROUND(ia.weighted_severity, 4)
                    )
                    ORDER BY ia.review_count DESC, ia.weighted_severity DESC, ia.label ASC
                )
            ) AS VARCHAR
        ) AS issue_breakdown_json
    FROM issue_agg ia
    JOIN base b USING (app_version)
    GROUP BY 1
),
category_agg AS (
    SELECT
        r.app_version,
        COALESCE(e.category_taxonomy, 'Other') AS category_taxonomy,
        COUNT(*) AS review_count
    FROM reviews_raw r
    JOIN reviews_enriched e USING (review_id)
    GROUP BY 1, 2
),
category_json AS (
    SELECT
        ca.app_version,
        CAST(
            to_json(
                list(
                    struct_pack(
                        category := ca.category_taxonomy,
                        review_count := ca.review_count,
                        pct_reviews := ROUND(ca.review_count::DOUBLE / NULLIF(b.total_reviews, 0), 4)
                    )
                    ORDER BY ca.review_count DESC, ca.category_taxonomy ASC
                )
            ) AS VARCHAR
        ) AS category_breakdown_json
    FROM category_agg ca
    JOIN base b USING (app_version)
    GROUP BY 1
)
SELECT
    b.app_version,
    b.first_seen_day,
    b.last_seen_day,
    b.total_reviews,
    ROUND(b.avg_rating, 4) AS avg_rating,
    ROUND(b.pct_negative, 4) AS pct_negative,
    b.critical_count,
    COALESCE(i.issue_breakdown_json, '[]') AS issue_breakdown_json,
    COALESCE(c.category_breakdown_json, '[]') AS category_breakdown_json
FROM base b
LEFT JOIN issue_json i USING (app_version)
LEFT JOIN category_json c USING (app_version)
ORDER BY b.app_version;
