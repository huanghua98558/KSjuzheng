-- Auto-generated from MCN spark_violation_dramas on 2026-04-21T02:04:49.138227
-- Rule: Type A (reason=不符合社区 AND SUM>=100) UNION Type C (空 reason AND SUM>=1000)
-- Total: 22 dramas

BEGIN TRANSACTION;

UPDATE drama_blacklist
SET status = 'active', violation_type = 'content_violation'
WHERE drama_name IN (
  '一代宗师之武神归来',
  '一切从无敌开始',
  '八零飒妻要发家',
  '前夫请自重',
  '北境战神',
  '只对她偏爱',
  '天降碎嘴小青梅11',
  '妻子的婚姻保卫战',
  '宝鉴',
  '寒门出贵子',
  '帝君',
  '我不做大哥很多年',
  '我是天师',
  '我的危险老公',
  '摊牌了我就是大小姐',
  '最后的旅程',
  '玄门老祖驾到',
  '破晓时分',
  '老婆大人别想逃',
  '花开盛夏正当时',
  '雾起时请爱上我',
  '陆总今天要离婚'
);

COMMIT;
