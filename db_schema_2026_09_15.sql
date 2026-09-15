CREATE TABLE `availability` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `match_id` int(11) NOT NULL,
  `player_id` int(11) NOT NULL,
  `status` enum('in','out','maybe') NOT NULL,
  `updated_at` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_player_match` (`match_id`,`player_id`),
  KEY `fk_availability_player` (`player_id`),
  CONSTRAINT `availability_ibfk_1` FOREIGN KEY (`match_id`) REFERENCES `matches` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_availability_player` FOREIGN KEY (`player_id`) REFERENCES `players` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=49 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `benefits` (
  `benefit_id` int(11) NOT NULL AUTO_INCREMENT,
  `benefit_name` varchar(100) NOT NULL,
  `description` varchar(500) NOT NULL,
  `handicap_credits` decimal(10,2) NOT NULL,
  `active` tinyint(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (`benefit_id`),
  UNIQUE KEY `unique_benefit_name` (`benefit_name`)
) ENGINE=InnoDB AUTO_INCREMENT=1031 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `bookie_balance` (
  `starting_balance` decimal(10,2) NOT NULL,
  `current_balance` decimal(10,2) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `bot_log` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `logged_at` datetime NOT NULL DEFAULT current_timestamp(),
  `severity` varchar(20) NOT NULL,
  `source` varchar(50) DEFAULT NULL,
  `message` text NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_bot_log_logged_at` (`logged_at`),
  KEY `idx_bot_log_severity` (`severity`),
  KEY `idx_bot_log_source` (`source`)
) ENGINE=InnoDB AUTO_INCREMENT=2254 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `bot_usage` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `used_at` datetime NOT NULL DEFAULT current_timestamp(),
  `command_name` varchar(50) NOT NULL,
  `discord_user_id` bigint(20) unsigned NOT NULL,
  `api_call` tinyint(1) NOT NULL DEFAULT 0,
  `input_tokens` int(10) unsigned DEFAULT NULL,
  `output_tokens` int(10) unsigned DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_bot_usage_used_at` (`used_at`),
  KEY `idx_bot_usage_command` (`command_name`),
  KEY `idx_bot_usage_user` (`discord_user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=405 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `gamblers` (
  `gambler_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `is_david` tinyint(1) NOT NULL DEFAULT 0,
  `risk_tolerance` tinyint(3) unsigned NOT NULL,
  `loss_aversion` tinyint(3) unsigned NOT NULL,
  `contrarianism` tinyint(3) unsigned NOT NULL,
  `confidence` tinyint(3) unsigned NOT NULL,
  `bankroll_discipline` tinyint(3) unsigned NOT NULL,
  `starting_balance` decimal(10,2) NOT NULL,
  `current_balance` decimal(10,2) NOT NULL,
  `personality` text DEFAULT NULL,
  PRIMARY KEY (`gambler_id`),
  CONSTRAINT `chk_risk_tolerance` CHECK (`risk_tolerance` between 0 and 100),
  CONSTRAINT `chk_loss_aversion` CHECK (`loss_aversion` between 0 and 100),
  CONSTRAINT `chk_contrarianism` CHECK (`contrarianism` between 0 and 100),
  CONSTRAINT `chk_confidence` CHECK (`confidence` between 0 and 100),
  CONSTRAINT `chk_bankroll_discipline` CHECK (`bankroll_discipline` between 0 and 100),
  CONSTRAINT `chk_starting_balance` CHECK (`starting_balance` >= 0)
) ENGINE=InnoDB AUTO_INCREMENT=501 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `market_prices` (
  `market_price_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `match_id` int(11) NOT NULL,
  `player_id` int(11) NOT NULL,
  `odds_american` int(11) NOT NULL,
  `reason` varchar(500) DEFAULT NULL,
  `effective_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`market_price_id`),
  KEY `fk_market_prices_match` (`match_id`),
  KEY `fk_market_prices_player` (`player_id`),
  CONSTRAINT `fk_market_prices_match` FOREIGN KEY (`match_id`) REFERENCES `matches` (`id`),
  CONSTRAINT `fk_market_prices_player` FOREIGN KEY (`player_id`) REFERENCES `players` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=193 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `match_groups` (
  `match_id` int(11) NOT NULL,
  `group_id` int(11) NOT NULL,
  `players_in_group` int(11) DEFAULT NULL,
  `total_points` int(11) DEFAULT NULL,
  `ending_hole` int(11) DEFAULT NULL,
  PRIMARY KEY (`match_id`,`group_id`),
  CONSTRAINT `fk_match_groups_match` FOREIGN KEY (`match_id`) REFERENCES `matches` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `match_results` (
  `match_id` int(11) NOT NULL,
  `group_id` int(11) NOT NULL,
  `player_id` int(11) NOT NULL,
  `player_points` int(11) DEFAULT NULL,
  `group_winner` tinyint(1) NOT NULL DEFAULT 0,
  `match_winner` tinyint(1) NOT NULL DEFAULT 0,
  `pre_match_index` decimal(10,2) DEFAULT NULL,
  `match_performance` decimal(10,2) DEFAULT NULL,
  `net_handicap_credits` decimal(10,2) DEFAULT NULL,
  PRIMARY KEY (`match_id`,`player_id`),
  KEY `fk_match_results_group` (`match_id`,`group_id`),
  KEY `fk_match_results_player` (`player_id`),
  CONSTRAINT `fk_match_results_group` FOREIGN KEY (`match_id`, `group_id`) REFERENCES `match_groups` (`match_id`, `group_id`),
  CONSTRAINT `fk_match_results_player` FOREIGN KEY (`player_id`) REFERENCES `players` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `matches` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `match_date` date NOT NULL,
  `location` varchar(255) DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `special_rule` text DEFAULT NULL,
  `active` tinyint(1) NOT NULL DEFAULT 1,
  `tee_time_1` time DEFAULT NULL,
  `tee_time_2` time DEFAULT NULL,
  `tee_time_3` time DEFAULT NULL,
  `tee_time_4` time DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `players` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `player_name` varchar(100) NOT NULL,
  `discord_user_id` bigint(20) unsigned DEFAULT NULL,
  `discord_username` varchar(100) DEFAULT NULL,
  `discord_display_name` varchar(100) DEFAULT NULL,
  `active` tinyint(1) NOT NULL DEFAULT 1,
  `bot_admin` tinyint(1) NOT NULL DEFAULT 0,
  `notes` text DEFAULT NULL,
  `quote` varchar(500) DEFAULT NULL,
  `normalized_cfb_index` decimal(10,2) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_player_name` (`player_name`),
  UNIQUE KEY `unique_discord_user` (`discord_user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `responses` (
  `response_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `match_id` int(11) DEFAULT NULL,
  `command` varchar(50) NOT NULL,
  `response_text` longtext NOT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`response_id`),
  KEY `idx_responses_match_command` (`match_id`,`command`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `wagers` (
  `wager_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `market_price_id` bigint(20) unsigned NOT NULL,
  `gambler_id` int(10) unsigned NOT NULL,
  `wagered_at` datetime NOT NULL DEFAULT current_timestamp(),
  `wager_amount` decimal(10,2) NOT NULL,
  `reason` varchar(500) DEFAULT NULL,
  `outcome` varchar(10) DEFAULT NULL,
  `payout` decimal(10,2) DEFAULT NULL,
  PRIMARY KEY (`wager_id`),
  KEY `fk_wagers_market_price` (`market_price_id`),
  KEY `fk_wagers_gambler` (`gambler_id`),
  CONSTRAINT `fk_wagers_gambler` FOREIGN KEY (`gambler_id`) REFERENCES `gamblers` (`gambler_id`),
  CONSTRAINT `fk_wagers_market_price` FOREIGN KEY (`market_price_id`) REFERENCES `market_prices` (`market_price_id`),
  CONSTRAINT `chk_wager_amount` CHECK (`wager_amount` > 0),
  CONSTRAINT `chk_wager_outcome` CHECK (`outcome` is null or `outcome` in ('WIN','LOSS'))
) ENGINE=InnoDB AUTO_INCREMENT=2470 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
