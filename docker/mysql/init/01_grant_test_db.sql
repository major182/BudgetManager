-- テスト実行時、Django は「test_budget」という別の DB を作ってから消す。
-- そのための権限を開発用の利用者に与える（コンテナの初回起動時にだけ実行される）
GRANT ALL PRIVILEGES ON `test\_budget`.* TO 'budget'@'%';
FLUSH PRIVILEGES;
