package com.sopiskill.core.gamification;

import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.config.SopiProperties;
import java.sql.Timestamp;
import java.time.DayOfWeek;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Weekly Leagues service: 5 tiers (`bronze -> silver -> gold -> sapphire -> ruby`),
 * max 30 learners per cohort, weekly promotion/demotion settlement, guarded by `LEAGUES_ENABLED`.
 */
@Service
public class LeagueService {

    public static final int COHORT_MAX_SIZE = 30;
    public static final List<String> TIERS = List.of("bronze", "silver", "gold", "sapphire", "ruby");

    private final JdbcClient jdbc;
    private final SopiProperties props;

    public LeagueService(JdbcClient jdbc, SopiProperties props) {
        this.jdbc = jdbc;
        this.props = props;
    }

    public static LocalDate currentWeekStart(Instant now) {
        return now.atOffset(ZoneOffset.UTC).toLocalDate()
                .with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
    }

    public static String nextTier(String tier) {
        int idx = TIERS.indexOf(tier);
        if (idx < 0 || idx >= TIERS.size() - 1) return TIERS.getLast();
        return TIERS.get(idx + 1);
    }

    public static String prevTier(String tier) {
        int idx = TIERS.indexOf(tier);
        if (idx <= 0) return TIERS.getFirst();
        return TIERS.get(idx - 1);
    }

    public void requireEnabled() {
        if (!props.leaguesEnabled()) {
            throw new ApiException(
                    HttpStatus.SERVICE_UNAVAILABLE,
                    "LEAGUES_DISABLED",
                    "Bảng xếp hạng tuần (Leagues) hiện chưa được bật."
            );
        }
    }

    /**
     * Enrolls the user into an open cohort for the current week (max 30 learners/cohort)
     * and adds weekly XP atomically inside the caller's transaction.
     */
    @Transactional
    public UUID ensureEnrolledAndAddXp(UUID userId, int xpDelta, Instant now) {
        LocalDate weekStart = currentWeekStart(now);
        var existingOpt = jdbc.sql("""
                SELECT lm.id, lm.cohort_id
                FROM core.league_memberships lm
                JOIN core.league_cohorts lc ON lc.id = lm.cohort_id
                WHERE lm.user_id = :uid AND lc.week_start = :ws
                LIMIT 1
                """)
                .param("uid", userId)
                .param("ws", weekStart)
                .query((rs, rowNum) -> Map.of(
                        "membershipId", rs.getObject("id", UUID.class),
                        "cohortId", rs.getObject("cohort_id", UUID.class)
                ))
                .optional();

        if (existingOpt.isPresent()) {
            UUID mid = existingOpt.get().get("membershipId");
            if (xpDelta > 0) {
                jdbc.sql("""
                        UPDATE core.league_memberships
                        SET weekly_xp = weekly_xp + :delta, updated_at = now()
                        WHERE id = :mid
                        """)
                        .param("delta", xpDelta)
                        .param("mid", mid)
                        .update();
            }
            return existingOpt.get().get("cohortId");
        }

        String tier = determineTargetTier(userId, weekStart);
        UUID cohortId = findOrCreateOpenCohort(tier, weekStart);

        jdbc.sql("""
                INSERT INTO core.league_memberships (id, cohort_id, user_id, weekly_xp)
                VALUES (:id, :cid, :uid, :xp)
                ON CONFLICT (cohort_id, user_id) DO UPDATE SET
                    weekly_xp = core.league_memberships.weekly_xp + EXCLUDED.weekly_xp,
                    updated_at = now()
                """)
                .param("id", UUID.randomUUID())
                .param("cid", cohortId)
                .param("uid", userId)
                .param("xp", Math.max(0, xpDelta))
                .update();

        return cohortId;
    }

    private String determineTargetTier(UUID userId, LocalDate currentWeekStart) {
        var lastOpt = jdbc.sql("""
                SELECT lc.tier, lm.outcome
                FROM core.league_memberships lm
                JOIN core.league_cohorts lc ON lc.id = lm.cohort_id
                WHERE lm.user_id = :uid AND lc.week_start < :ws AND lc.settled = TRUE
                ORDER BY lc.week_start DESC
                LIMIT 1
                """)
                .param("uid", userId)
                .param("ws", currentWeekStart)
                .query((rs, rowNum) -> Map.of(
                        "tier", rs.getString("tier"),
                        "outcome", rs.getString("outcome") == null ? "stayed" : rs.getString("outcome")
                ))
                .optional();

        if (lastOpt.isEmpty()) {
            return "bronze";
        }
        String lastTier = lastOpt.get().get("tier");
        String outcome = lastOpt.get().get("outcome");
        return switch (outcome) {
            case "promoted" -> nextTier(lastTier);
            case "demoted" -> prevTier(lastTier);
            default -> lastTier;
        };
    }

    private UUID findOrCreateOpenCohort(String tier, LocalDate weekStart) {
        // Lock existing unsettled cohorts for this tier/week so concurrent joins never exceed 30 members
        List<UUID> candidateCohorts = jdbc.sql("""
                SELECT lc.id
                FROM core.league_cohorts lc
                WHERE lc.tier = :tier AND lc.week_start = :ws AND lc.settled = FALSE
                ORDER BY lc.created_at ASC
                FOR UPDATE
                """)
                .param("tier", tier)
                .param("ws", weekStart)
                .query(UUID.class)
                .list();

        for (UUID cohortId : candidateCohorts) {
            Integer count = jdbc.sql("SELECT COUNT(*) FROM core.league_memberships WHERE cohort_id = :cid")
                    .param("cid", cohortId)
                    .query(Integer.class)
                    .single();
            if (count != null && count < COHORT_MAX_SIZE) {
                return cohortId;
            }
        }

        UUID newCohortId = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO core.league_cohorts (id, tier, week_start, settled)
                VALUES (:id, :tier, :ws, FALSE)
                """)
                .param("id", newCohortId)
                .param("tier", tier)
                .param("ws", weekStart)
                .update();
        return newCohortId;
    }

    /**
     * Settles all unsettled cohorts for the given weekStart:
     * ranks members by `weekly_xp DESC, joined_at ASC`, promotes top 20% (except ruby),
     * demotes bottom 20% (except bronze when cohort size >= 5), keeps others `stayed`.
     */
    @Transactional
    public int settleWeek(LocalDate weekStart, Instant now) {
        List<Map<String, Object>> cohorts = jdbc.sql("""
                SELECT id, tier
                FROM core.league_cohorts
                WHERE week_start = :ws AND settled = FALSE
                FOR UPDATE
                """)
                .param("ws", weekStart)
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "id", rs.getObject("id", UUID.class),
                        "tier", rs.getString("tier")
                ))
                .list();

        int settledCount = 0;
        for (Map<String, Object> cohort : cohorts) {
            UUID cohortId = (UUID) cohort.get("id");
            String tier = String.valueOf(cohort.get("tier"));
            List<UUID> memberIds = jdbc.sql("""
                    SELECT id
                    FROM core.league_memberships
                    WHERE cohort_id = :cid
                    ORDER BY weekly_xp DESC, joined_at ASC
                    FOR UPDATE
                    """)
                    .param("cid", cohortId)
                    .query(UUID.class)
                    .list();

            int n = memberIds.size();
            int promoteSlots = !"ruby".equals(tier) && n >= 3 ? Math.max(1, (int) Math.floor(n * 0.2)) : 0;
            int demoteSlots = !"bronze".equals(tier) && n >= 5 ? Math.max(1, (int) Math.floor(n * 0.2)) : 0;

            for (int i = 0; i < n; i++) {
                int rank = i + 1;
                String outcome = "stayed";
                if (rank <= promoteSlots) {
                    outcome = "promoted";
                } else if (demoteSlots > 0 && rank > n - demoteSlots) {
                    outcome = "demoted";
                }
                jdbc.sql("""
                        UPDATE core.league_memberships
                        SET rank = :rank, outcome = :outcome, updated_at = now()
                        WHERE id = :mid
                        """)
                        .param("rank", rank)
                        .param("outcome", outcome)
                        .param("mid", memberIds.get(i))
                        .update();
            }

            jdbc.sql("""
                    UPDATE core.league_cohorts
                    SET settled = TRUE, settled_at = :now
                    WHERE id = :cid
                    """)
                    .param("now", Timestamp.from(now))
                    .param("cid", cohortId)
                    .update();
            settledCount++;
        }
        return settledCount;
    }

    @Transactional
    public Map<String, Object> getCurrentLeague(UUID userId, Instant now) {
        requireEnabled();
        UUID cohortId = ensureEnrolledAndAddXp(userId, 0, now);
        return buildCohortView(cohortId, userId);
    }

    public Map<String, Object> getLastLeague(UUID userId, Instant now) {
        requireEnabled();
        LocalDate currentWs = currentWeekStart(now);
        var lastOpt = jdbc.sql("""
                SELECT lc.id
                FROM core.league_memberships lm
                JOIN core.league_cohorts lc ON lc.id = lm.cohort_id
                WHERE lm.user_id = :uid AND (lc.settled = TRUE OR lc.week_start < :ws)
                ORDER BY lc.week_start DESC, lc.created_at DESC
                LIMIT 1
                """)
                .param("uid", userId)
                .param("ws", currentWs)
                .query(UUID.class)
                .optional();

        if (lastOpt.isEmpty()) {
            Map<String, Object> empty = new LinkedHashMap<>();
            empty.put("hasPrevious", false);
            empty.put("cohort", null);
            return empty;
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("hasPrevious", true);
        out.put("cohort", buildCohortView(lastOpt.get(), userId));
        return out;
    }

    private Map<String, Object> buildCohortView(UUID cohortId, UUID viewerId) {
        var cohort = jdbc.sql("""
                SELECT id, tier, week_start, settled, settled_at
                FROM core.league_cohorts
                WHERE id = :cid
                """)
                .param("cid", cohortId)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("cohortId", IdCodec.format("lgc", rs.getObject("id", UUID.class)));
                    m.put("tier", rs.getString("tier"));
                    m.put("weekStart", rs.getDate("week_start").toLocalDate().toString());
                    m.put("settled", rs.getBoolean("settled"));
                    var sa = rs.getTimestamp("settled_at");
                    m.put("settledAt", sa == null ? null : sa.toInstant().toString());
                    return m;
                })
                .single();

        List<Map<String, Object>> rows = jdbc.sql("""
                SELECT lm.id, lm.user_id, u.display_name, lm.weekly_xp, lm.rank, lm.outcome
                FROM core.league_memberships lm
                JOIN core.users u ON u.id = lm.user_id
                WHERE lm.cohort_id = :cid
                ORDER BY lm.weekly_xp DESC, lm.joined_at ASC
                """)
                .param("cid", cohortId)
                .query((rs, rowNum) -> {
                    UUID uid = rs.getObject("user_id", UUID.class);
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("membershipId", IdCodec.format("lgm", rs.getObject("id", UUID.class)));
                    m.put("userId", IdCodec.format("usr", uid));
                    m.put("displayName", rs.getString("display_name"));
                    m.put("weeklyXp", rs.getInt("weekly_xp"));
                    m.put("rank", rs.getObject("rank") != null ? rs.getInt("rank") : rowNum + 1);
                    m.put("outcome", rs.getString("outcome"));
                    m.put("isMe", uid.equals(viewerId));
                    return m;
                })
                .list();

        int n = rows.size();
        String tier = String.valueOf(cohort.get("tier"));
        int promotionZone = !"ruby".equals(tier) && n >= 3 ? Math.max(1, (int) Math.floor(n * 0.2)) : 0;
        int demotionZone = !"bronze".equals(tier) && n >= 5 ? Math.max(1, (int) Math.floor(n * 0.2)) : 0;

        Integer myRank = null;
        String myOutcome = null;
        int myWeeklyXp = 0;
        List<Map<String, Object>> standings = new ArrayList<>(n);
        for (int i = 0; i < n; i++) {
            Map<String, Object> row = new LinkedHashMap<>(rows.get(i));
            int rank = ((Number) row.get("rank")).intValue();
            String zone = "stay";
            if (promotionZone > 0 && rank <= promotionZone) zone = "promotion";
            else if (demotionZone > 0 && rank > n - demotionZone) zone = "demotion";
            row.put("zone", zone);
            standings.add(row);
            if (Boolean.TRUE.equals(row.get("isMe"))) {
                myRank = rank;
                myOutcome = (String) row.get("outcome");
                myWeeklyXp = ((Number) row.get("weeklyXp")).intValue();
            }
        }

        cohort.put("tiers", TIERS);
        cohort.put("cohortMaxSize", COHORT_MAX_SIZE);
        cohort.put("memberCount", n);
        cohort.put("promotionZone", promotionZone);
        cohort.put("demotionZone", demotionZone);
        cohort.put("myRank", myRank);
        cohort.put("myWeeklyXp", myWeeklyXp);
        cohort.put("myOutcome", myOutcome);
        cohort.put("standings", standings);
        return cohort;
    }
}
