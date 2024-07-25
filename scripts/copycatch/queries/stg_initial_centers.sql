WITH
  df1 AS (
  SELECT
    repo_name,
    COUNT(actor) AS n_stars,
    AVG(UNIX_SECONDS(starred_at)) AS repo_center,
  FROM
    `socket-research.fake_stars.stargazers_*`
  WHERE
    ENDS_WITH(_TABLE_SUFFIX, CONCAT(@start_date, '_', @end_date))
  GROUP BY
    repo_name
  HAVING
    n_stars >= @min_stars_copycatch_seed)
SELECT
  *,
  JSON_OBJECT(repo_name, repo_center) AS centers,
  [repo_name] AS clusters,
FROM
  df1