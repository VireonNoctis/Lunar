from _future_ import annotations
import asyncio
import json
import logging
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import (
    Any,
    Iterable,
    Mapping,
    Optional,
    Sequence,
)

from cassandra import ConsistencyLevel
from cassandra.auth import PlainTextAuthProvider
from cassandra.cluster import Cluster, Session
from cassandra.policies import (
    DCAwareRoundRobinPolicy,
    TokenAwarePolicy,
)
from cassandra.query import (
    BatchStatement,
    BatchType,
    PreparedStatement,
    SimpleStatement,
)


# ============================================================
# LOGGING
# ============================================================

log = logging.getLogger("lunar.database")


# ============================================================
# HELPERS
# ============================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def json_loads(
    value: Any,
    default: Any = None,
) -> Any:
    if value is None:
        return default

    if isinstance(value, (dict, list)):
        return value

    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# ============================================================
# CONFIGURATION
# ============================================================

@dataclass(slots=True)
class ScyllaConfig:
    hosts: tuple[str, ...] = (
        "127.0.0.1",
    )

    port: int = 9042

    username: Optional[str] = None
    password: Optional[str] = None

    keyspace: str = "lunar"

    local_dc: Optional[str] = None

    replication_factor: int = 1

    connect_timeout: float = 10.0

    request_timeout: float = 15.0


# ============================================================
# DATABASE CONFIG
# ============================================================

SCYLLA_CONFIG = ScyllaConfig(
    hosts=(
        "127.0.0.1",
        # "127.0.0.2",
        # "127.0.0.3",
    ),

    port=9042,

    username=None,
    password=None,

    keyspace="lunar",

    # Example:
    #
    # local_dc="datacenter1"
    #
    local_dc=None,

    replication_factor=1,

    connect_timeout=10.0,
    request_timeout=15.0,
)


# ============================================================
# CORE SCHEMA
# ============================================================

CORE_SCHEMA: tuple[str, ...] = (

    # ========================================================
    # BOT VARIABLES
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS variables (
        identifier text PRIMARY KEY,

        int_value bigint,
        string_value text,

        metadata map<text, text>
    )
    """,

    # ========================================================
    # COMMAND COUNTERS
    # ========================================================
    #
    # Counters are intentionally isolated from regular columns.
    #
    # command_counters:
    #     high-volume usage counter
    #
    # command_usage_meta:
    #     metadata that cannot live inside a counter table
    #
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS command_counters (
        command_name text PRIMARY KEY,

        uses counter
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS command_usage_meta (
        command_name text PRIMARY KEY,

        last_used_at timestamp
    )
    """,

    # ========================================================
    # USERS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS users (
        snowflake_id text PRIMARY KEY,

        level int,
        required_xp int,
        xp bigint,
        shame_points int,

        is_active boolean,
        is_banned boolean,

        username text,
        display_name text,

        created_at timestamp,
        updated_at timestamp,
        last_seen_at timestamp,

        metadata map<text, text>
    )
    """,

    # ========================================================
    # ACCOUNT LINKS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS account_links (
        snowflake_id text PRIMARY KEY,

        lunar_uuid uuid,

        verification_code text,

        verified boolean,

        last_message_time timestamp,

        verified_at timestamp,
        created_at timestamp,
        updated_at timestamp,

        metadata map<text, text>
    )
    """,

    # ========================================================
    # ACCOUNT LINKS BY LUNAR UUID
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS account_links_by_uuid (
        lunar_uuid uuid PRIMARY KEY,

        snowflake_id text,

        verification_code text,

        verified boolean,

        last_message_time timestamp,

        verified_at timestamp,
        created_at timestamp,
        updated_at timestamp,

        metadata map<text, text>
    )
    """,

    # ========================================================
    # XP EVENTS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS xp_events (
        snowflake_id text,
        event_date date,
        event_id timeuuid,

        amount bigint,
        reason text,

        guild_id text,
        channel_id text,

        balance_after bigint,

        metadata map<text, text>,

        PRIMARY KEY (
            snowflake_id,
            event_date,
            event_id
        )
    )
    WITH CLUSTERING ORDER BY (
        event_id DESC
    )
    """,

    # ========================================================
    # SHAME EVENTS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS shame_events (
        snowflake_id text,
        event_date date,
        event_id timeuuid,

        amount int,
        reason text,

        moderator_id text,
        guild_id text,

        metadata map<text, text>,

        PRIMARY KEY (
            snowflake_id,
            event_date,
            event_id
        )
    )
    WITH CLUSTERING ORDER BY (
        event_id DESC
    )
    """,

    # ========================================================
    # GUILDS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS guilds (
        guild_id text PRIMARY KEY,

        name text,

        enabled boolean,

        prefix text,

        log_channel_id text,
        welcome_channel_id text,

        created_at timestamp,
        updated_at timestamp,

        metadata map<text, text>
    )
    """,

    # ========================================================
    # GUILD MEMBERS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS guild_members (
        guild_id text,
        snowflake_id text,

        joined_at timestamp,
        last_seen_at timestamp,

        xp_enabled boolean,

        metadata map<text, text>,

        PRIMARY KEY (
            guild_id,
            snowflake_id
        )
    )
    """,

    # ========================================================
    # SETTINGS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS settings (
        scope text,
        scope_id text,
        setting text,

        value text,

        updated_at timestamp,

        PRIMARY KEY (
            scope,
            scope_id,
            setting
        )
    )
    """,

    
    # ========================================================
    # SETTINGS
    # ========================================================
    """
CREATE TABLE IF NOT EXISTS leaderboard_message_hourly (
    guild_id text,
    hour_bucket text,
    user_id text,
    message_count counter,
    PRIMARY KEY ((guild_id, hour_bucket), user_id)
)
""",

"""
CREATE TABLE IF NOT EXISTS leaderboard_message_totals (
    guild_id text,
    user_id text,
    message_count counter,
    PRIMARY KEY ((guild_id), user_id)
)
""",

"""
CREATE TABLE IF NOT EXISTS leaderboard_vc_totals (
    guild_id text,
    user_id text,
    seconds counter,
    PRIMARY KEY ((guild_id), user_id)
)
""",

"""
CREATE TABLE IF NOT EXISTS leaderboard_vc_active (
    guild_id text,
    user_id text,
    joined_at timestamp,
    PRIMARY KEY ((guild_id), user_id)
)
""",

"""
CREATE TABLE IF NOT EXISTS leaderboard_sync_state (
    guild_id text PRIMARY KEY,
    last_sync_at timestamp,
    messages_scanned bigint,
    channels_scanned int,
    users_discovered int
)
""",
    # ========================================================
    # FEATURE FLAGS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS feature_flags (
        scope text,
        scope_id text,
        feature text,

        enabled boolean,

        updated_at timestamp,

        metadata map<text, text>,

        PRIMARY KEY (
            scope,
            scope_id,
            feature
        )
    )
    """,

    # ========================================================
    # COOLDOWNS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS cooldowns (
        scope text,
        scope_id text,
        command text,

        expires_at timestamp,

        PRIMARY KEY (
            scope,
            scope_id,
            command
        )
    )
    """,

    # ========================================================
    # AUDIT LOGS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        guild_id text,
        event_date date,
        event_id timeuuid,

        actor_id text,

        action text,
        target_id text,

        reason text,

        metadata map<text, text>,

        PRIMARY KEY (
            guild_id,
            event_date,
            event_id
        )
    )
    WITH CLUSTERING ORDER BY (
        event_id DESC
    )
    """,

    # ========================================================
    # BOT COUNTERS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS bot_counters (
        stat_name text PRIMARY KEY,

        value counter
    )
    """,

    # ========================================================
    # GITHUB REPOSITORIES
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS github_repositories (
        repository text PRIMARY KEY,

        url text,

        owner text,
        name text,
        branch text,

        channel_id text,

        enabled boolean,

        last_commit_sha text,
        last_checked_at timestamp,

        metadata map<text, text>
    )
    """,

    # ========================================================
    # GITHUB COMMITS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS github_commits (
        repository text,
        committed_date date,
        committed_at timestamp,
        sha text,

        author text,
        committer text,

        message text,

        branch text,

        verified boolean,

        additions int,
        deletions int,
        changed_files int,

        html_url text,

        files list<text>,

        metadata map<text, text>,

        PRIMARY KEY (
            repository,
            committed_date,
            committed_at,
            sha
        )
    )
    WITH CLUSTERING ORDER BY (
        committed_at DESC
    )
    """,

    # ========================================================
    # GITHUB ISSUES
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS github_issues (
        repository text,
        issue_number int,

        title text,
        body text,

        author_id text,

        html_url text,

        state text,
        issue_type text,

        created_at timestamp,

        metadata map<text, text>,

        PRIMARY KEY (
            repository,
            issue_number
        )
    )
    """,

    # ========================================================
    # EXTENSION STORAGE
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS extension_data (
        namespace text,
        entity_id text,
        key text,

        value text,

        updated_at timestamp,

        expires_at timestamp,

        metadata map<text, text>,

        PRIMARY KEY (
            namespace,
            entity_id,
            key
        )
    )
    """,

    # ========================================================
    # MENTIONS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS mentions_by_user (
        mentioned_id text,
        archived boolean,
        is_read boolean,

        created_at timestamp,
        id uuid,

        message_id text,
        message_author_id text,
        channel_id text,
        guild_id text,

        PRIMARY KEY (
            (mentioned_id, archived, is_read),
            created_at,
            id
        )
    )
    WITH CLUSTERING ORDER BY (
        created_at DESC,
        id DESC
    )
    """,

    # ========================================================
    # GIVEAWAYS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS giveaways (
        giveaway_id text PRIMARY KEY,

        message_id text,
        channel_id text,
        guild_id text,

        host_id text,

        duration_seconds bigint,

        prize text,
        description text,

        winners_count int,

        participant_ids set<text>,
        winner_ids set<text>,

        state text,

        created_at timestamp,
        ends_at timestamp,
        ended_at timestamp,

        metadata map<text, text>
    )
    """,

    # ========================================================
    # GIVEAWAYS BY MESSAGE
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS giveaways_by_message (
        message_id text PRIMARY KEY,

        giveaway_id text
    )
    """,

    # ========================================================
    # ACTIVE GIVEAWAYS
    # ========================================================

    """
    CREATE TABLE IF NOT EXISTS giveaways_active (
        bucket text,
        ends_at timestamp,
        giveaway_id text,

        PRIMARY KEY (
            bucket,
            ends_at,
            giveaway_id
        )
    )
    WITH CLUSTERING ORDER BY (
        ends_at ASC
    )
    """,
)


# ============================================================
# DATABASE ENGINE
# ============================================================

class ScyllaDatabase:

    def __init__(
        self,
        config: ScyllaConfig,
    ):
        self.config = config

        self.cluster: Optional[Cluster] = None
        self.session: Optional[Session] = None

        self._initialized = False
        self._lock = asyncio.Lock()

        self._prepared: dict[
            str,
            PreparedStatement,
        ] = {}

        # ----------------------------------------------------
        # REPOSITORIES
        # ----------------------------------------------------

        self.users: Optional[UserRepository] = None

        self.account_links: Optional[
            AccountLinkRepository
        ] = None

        self.command_stats: Optional[
            CommandStatsRepository
        ] = None

        self.xp: Optional[
            XPRepository
        ] = None

        self.shame: Optional[
            ShameRepository
        ] = None

        self.guilds: Optional[
            GuildRepository
        ] = None

        self.settings: Optional[
            SettingsRepository
        ] = None

        self.flags: Optional[
            FeatureFlagRepository
        ] = None

        self.cooldowns: Optional[
            CooldownRepository
        ] = None

        self.audit: Optional[
            AuditRepository
        ] = None

        self.stats: Optional[
            StatsRepository
        ] = None

        self.github: Optional[
            GitHubRepository
        ] = None

        self.extensions: Optional[
            ExtensionRepository
        ] = None

        self.mentions: Optional[
            MentionRepository
        ] = None

        self.variables: Optional[
            VariableRepository
        ] = None

        self.giveaways: Optional[
            GiveawayRepository
        ] = None

    # ========================================================
    # INITIALIZATION
    # ========================================================

    async def initialize(self):
        async with self._lock:

            if self._initialized:
                return

            auth_provider = None

            if (
                self.config.username
                and self.config.password
            ):
                auth_provider = PlainTextAuthProvider(
                    username=self.config.username,
                    password=self.config.password,
                )

            kwargs: dict[str, Any] = {
                "contact_points": list(
                    self.config.hosts
                ),
                "port": self.config.port,
                "auth_provider": auth_provider,
                "connect_timeout": (
                    self.config.connect_timeout
                ),
                "control_connection_timeout": (
                    self.config.connect_timeout
                ),
            }

            if self.config.local_dc:

                kwargs[
                    "load_balancing_policy"
                ] = TokenAwarePolicy(
                    DCAwareRoundRobinPolicy(
                        local_dc=self.config.local_dc,
                        used_hosts_per_remote_dc=0,
                    )
                )

            self.cluster = Cluster(
                **kwargs
            )

            self.session = await asyncio.to_thread(
                self.cluster.connect
            )

            await asyncio.to_thread(
                self._create_keyspace
            )

            await asyncio.to_thread(
                self._switch_keyspace
            )

            await self._initialize_schema()

            self._bind_repositories()

            self._initialized = True

            log.info(
                "Scylla initialized "
                "keyspace=%s hosts=%s",
                self.config.keyspace,
                ",".join(self.config.hosts),
            )

    # ========================================================
    # REQUIRE INITIALIZATION
    # ========================================================

    def require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError(
                "Scylla database has not been initialized."
            )

    # ========================================================
    # KEYSPACE
    # ========================================================

    def _create_keyspace(self):

        if self.session is None:
            raise RuntimeError(
                "Scylla session does not exist."
            )

        if self.config.local_dc:

            replication = (
                "{"
                "'class': "
                "'NetworkTopologyStrategy', "
                f"'{self.config.local_dc}': "
                f"{self.config.replication_factor}"
                "}"
            )

        else:

            replication = (
                "{"
                "'class': 'SimpleStrategy', "
                "'replication_factor': "
                f"{self.config.replication_factor}"
                "}"
            )

        query = f"""
        CREATE KEYSPACE IF NOT EXISTS
        {self.config.keyspace}
        WITH replication = {replication}
        """

        self.session.execute(query)

    def _switch_keyspace(self):

        if self.cluster is None:
            raise RuntimeError(
                "Cluster is not initialized."
            )

        if self.session:
            self.session.shutdown()

        self.session = self.cluster.connect(
            self.config.keyspace
        )

        self.session.default_consistency_level = (
            ConsistencyLevel.LOCAL_QUORUM
        )

    # ========================================================
    # SCHEMA
    # ========================================================

    async def _initialize_schema(self):

        for statement in CORE_SCHEMA:

            await self.execute(
                statement
            )

    # ========================================================
    # REPOSITORY BINDING
    # ========================================================

    def _bind_repositories(self):

        self.users = UserRepository(self)

        self.account_links = (
            AccountLinkRepository(self)
        )

        self.command_stats = (
            CommandStatsRepository(self)
        )

        self.xp = XPRepository(self)

        self.shame = ShameRepository(self)

        self.guilds = GuildRepository(self)

        self.settings = SettingsRepository(self)

        self.flags = FeatureFlagRepository(self)

        self.cooldowns = CooldownRepository(self)

        self.audit = AuditRepository(self)

        self.stats = StatsRepository(self)

        self.github = GitHubRepository(self)

        self.extensions = ExtensionRepository(self)

        self.mentions = MentionRepository(self)

        self.variables = VariableRepository(self)

        self.giveaways = GiveawayRepository(self)

        self.leaderboard = LeaderboardRepository(self)

        
    # ========================================================
    # PREPARED STATEMENTS
    # ========================================================

    async def prepare(
        self,
        query: str,
    ) -> PreparedStatement:

        if self.session is None:
            raise RuntimeError(
                "Database is not initialized."
            )

        cached = self._prepared.get(query)

        if cached:
            return cached

        statement = await asyncio.to_thread(
            self.session.prepare,
            query,
        )

        self._prepared[query] = statement

        return statement

    # ========================================================
    # GENERIC EXECUTION
    # ========================================================

    async def execute(
        self,
        query: str,
        parameters: Optional[
            Sequence[Any]
        ] = None,
        *,
        consistency: Optional[
            ConsistencyLevel
        ] = None,
    ):

        if self.session is None:
            raise RuntimeError(
                "Database is not initialized."
            )

        statement = SimpleStatement(
            query,
            consistency_level=(
                consistency
                or ConsistencyLevel.LOCAL_QUORUM
            ),
        )

        return await asyncio.to_thread(
            self.session.execute,
            statement,
            parameters or (),
            timeout=self.config.request_timeout,
        )

    async def execute_prepared(
        self,
        query: str,
        parameters: Sequence[Any],
        *,
        consistency: Optional[
            ConsistencyLevel
        ] = None,
    ):

        statement = await self.prepare(
            query
        )

        if consistency is not None:
            statement.consistency_level = (
                consistency
            )

        if self.session is None:
            raise RuntimeError(
                "Database is not initialized."
            )

        return await asyncio.to_thread(
            self.session.execute,
            statement,
            parameters,
            timeout=self.config.request_timeout,
        )

    # ========================================================
    # BATCH
    # ========================================================

    async def batch(
        self,
        queries: Sequence[
            tuple[str, Sequence[Any]]
        ],
        *,
        logged: bool = False,
    ):

        if self.session is None:
            raise RuntimeError(
                "Database is not initialized."
            )

        batch_type = (
            BatchType.LOGGED
            if logged
            else BatchType.UNLOGGED
        )

        batch = BatchStatement(
            batch_type=batch_type,
            consistency_level=(
                ConsistencyLevel.LOCAL_QUORUM
            ),
        )

        for query, parameters in queries:

            prepared = await self.prepare(
                query
            )

            batch.add(
                prepared,
                parameters,
            )

        return await asyncio.to_thread(
            self.session.execute,
            batch,
        )

    # ========================================================
    # HEALTH
    # ========================================================

    async def ping(self) -> bool:

        try:

            result = await self.execute(
                """
                SELECT release_version
                FROM system.local
                """
            )

            return result.one() is not None

        except Exception as error:

            log.error(
                "Scylla health check failed: %s",
                error,
            )

            return False

    # ========================================================
    # STATUS
    # ========================================================

    async def status(self) -> dict[str, Any]:

        status: dict[str, Any] = {
            "initialized": self._initialized,

            "keyspace": self.config.keyspace,

            "hosts": self.config.hosts,

            "port": self.config.port,

            "local_dc": self.config.local_dc,

            "prepared_statements": len(
                self._prepared
            ),

            "cluster_connected": (
                self.cluster is not None
            ),

            "session_connected": (
                self.session is not None
            ),

            "repositories": [],
        }

        repositories = (
            "users",
            "account_links",
            "command_stats",
            "xp",
            "shame",
            "guilds",
            "settings",
            "flags",
            "cooldowns",
            "audit",
            "stats",
            "github",
            "extensions",
            "mentions",
            "variables",
            "giveaways",
        )

        status["repositories"] = [
            name
            for name in repositories
            if getattr(
                self,
                name,
                None,
            ) is not None
        ]

        try:

            result = await self.execute(
                """
                SELECT
                    cluster_name,
                    data_center,
                    release_version,
                    host_id
                FROM system.local
                """
            )

            row = result.one()

            if row:

                status["cluster_name"] = (
                    row.cluster_name
                )

                status["data_center"] = (
                    row.data_center
                )

                status["release_version"] = (
                    row.release_version
                )

                status["host_id"] = (
                    str(row.host_id)
                )

            status["healthy"] = True

        except Exception as exc:

            status["healthy"] = False

            status["error"] = str(exc)

        return status

    # ========================================================
    # CLOSE
    # ========================================================

    async def close(self):

        async with self._lock:

            if self.session:

                await asyncio.to_thread(
                    self.session.shutdown
                )

                self.session = None

            if self.cluster:

                await asyncio.to_thread(
                    self.cluster.shutdown
                )

                self.cluster = None

            self._prepared.clear()

            self._initialized = False


# ============================================================
# BASE REPOSITORY
# ============================================================

class BaseRepository:

    def __init__(
        self,
        database: ScyllaDatabase,
    ):
        self.db = database

    async def query(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ):
        return await self.db.execute(
            query,
            parameters,
        )

    async def one(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ):
        result = await self.query(
            query,
            parameters,
        )

        return result.one()

    async def all(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ):
        result = await self.query(
            query,
            parameters,
        )

        return result.all()


# ============================================================
# USERS
# ============================================================

class UserRepository(BaseRepository):

    async def create(
        self,
        snowflake_id: int | str,
        *,
        level: int = 1,
        required_xp: int = 100,
        xp: int = 0,
        shame_points: int = 0,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ):

        now = utcnow()

        await self.query(
            """
            INSERT INTO users (
                snowflake_id,
                level,
                required_xp,
                xp,
                shame_points,
                is_active,
                is_banned,
                username,
                display_name,
                created_at,
                updated_at,
                last_seen_at,
                metadata
            )
            VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?
            )
            """,
            (
                str(snowflake_id),
                level,
                required_xp,
                xp,
                shame_points,
                True,
                False,
                username,
                display_name,
                now,
                now,
                now,
                dict(metadata or {}),
            ),
        )

    async def get(
        self,
        snowflake_id: int | str,
    ):

        return await self.one(
            """
            SELECT *
            FROM users
            WHERE snowflake_id = ?
            """,
            (
                str(snowflake_id),
            ),
        )

    async def exists(
        self,
        snowflake_id: int | str,
    ) -> bool:

        return (
            await self.get(
                snowflake_id
            )
        ) is not None

    async def ensure(
        self,
        snowflake_id: int | str,
        **kwargs,
    ):

        existing = await self.get(
            snowflake_id
        )

        if existing:
            return existing

        await self.create(
            snowflake_id,
            **kwargs,
        )

        return await self.get(
            snowflake_id
        )

    async def update(
        self,
        snowflake_id: int | str,
        **fields,
    ):

        allowed = {
            "level",
            "required_xp",
            "xp",
            "shame_points",
            "username",
            "display_name",
            "is_active",
            "is_banned",
            "last_seen_at",
            "metadata",
        }

        updates = []
        values = []

        for key, value in fields.items():

            if key not in allowed:
                continue

            updates.append(
                f"{key} = ?"
            )

            values.append(value)

        if not updates:
            return

        updates.append(
            "updated_at = ?"
        )

        values.append(
            utcnow()
        )

        values.append(
            str(snowflake_id)
        )

        await self.query(
            f"""
            UPDATE users
            SET {", ".join(updates)}
            WHERE snowflake_id = ?
            """,
            values,
        )

    async def set_xp(
        self,
        snowflake_id: int | str,
        xp: int,
    ):

        await self.update(
            snowflake_id,
            xp=xp,
        )

    async def add_xp(
        self,
        snowflake_id: int | str,
        amount: int,
        *,
        reason: str = "unknown",
        guild_id: Optional[int | str] = None,
        channel_id: Optional[int | str] = None,
    ):

        user = await self.get(
            snowflake_id
        )

        if not user:

            await self.create(
                snowflake_id
            )

            user = await self.get(
                snowflake_id
            )

        current_xp = int(
            user.xp or 0
        )

        new_xp = (
            current_xp + amount
        )

        required_xp = int(
            user.required_xp or 100
        )

        level = int(
            user.level or 1
        )

        while (
            new_xp >= required_xp
            and required_xp > 0
        ):

            new_xp -= required_xp

            level += 1

            required_xp = max(
                required_xp + 1,
                int(
                    required_xp * 1.15
                ),
            )

        now = utcnow()

        await self.query(
            """
            UPDATE users
            SET
                xp = ?,
                level = ?,
                required_xp = ?,
                updated_at = ?,
                last_seen_at = ?
            WHERE snowflake_id = ?
            """,
            (
                new_xp,
                level,
                required_xp,
                now,
                now,
                str(snowflake_id),
            ),
        )

        if self.db.xp is not None:

            await self.db.xp.record(
                snowflake_id,
                amount=amount,
                reason=reason,
                guild_id=guild_id,
                channel_id=channel_id,
                balance_after=new_xp,
            )

        return await self.get(
            snowflake_id
        )

    async def add_shame(
        self,
        snowflake_id: int | str,
        amount: int,
    ):

        await self.query(
            """
            UPDATE users
            SET
                shame_points =
                    shame_points + ?,
                updated_at = ?
            WHERE snowflake_id = ?
            """,
            (
                amount,
                utcnow(),
                str(snowflake_id),
            ),
        )


# ============================================================
# ACCOUNT LINKS
# ============================================================

class AccountLinkRepository(BaseRepository):

    async def get(
        self,
        snowflake_id: int | str,
    ):

        return await self.one(
            """
            SELECT *
            FROM account_links
            WHERE snowflake_id = ?
            """,
            (
                str(snowflake_id),
            ),
        )

    async def get_by_lunar_uuid(
        self,
        lunar_uuid: str | uuid.UUID,
    ):

        parsed_uuid = uuid.UUID(
            str(lunar_uuid)
        )

        return await self.one(
            """
            SELECT *
            FROM account_links_by_uuid
            WHERE lunar_uuid = ?
            """,
            (
                parsed_uuid,
            ),
        )

    async def get_username(
        self,
        snowflake_id: int | str,
    ) -> str | None:

        account = await self.get(
            snowflake_id
        )

        if not account:
            return None

        metadata = (
            getattr(
                account,
                "metadata",
                None,
            )
            or {}
        )

        username = (
            metadata.get("username")
            or metadata.get("lunar_username")
        )

        if not isinstance(
            username,
            str,
        ):
            return None

        username = username.strip()

        return (
            username
            if username
            else None
        )

    async def link(
        self,
        snowflake_id: int | str,
        lunar_uuid: str | uuid.UUID,
        verification_code: str,
        *,
        verified: bool = False,
        last_message_time: Optional[
            datetime
        ] = None,
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ):

        discord_id = str(
            snowflake_id
        )

        parsed_uuid = uuid.UUID(
            str(lunar_uuid)
        )

        now = utcnow()

        # ----------------------------------------------------
        # EXISTING DISCORD ACCOUNT
        # ----------------------------------------------------

        existing = await self.get(
            discord_id
        )

        # ----------------------------------------------------
        # PREVENT DUPLICATE LUNAR LINK
        # ----------------------------------------------------

        uuid_owner = await self.get_by_lunar_uuid(
            parsed_uuid
        )

        if (
            uuid_owner
            and str(
                getattr(
                    uuid_owner,
                    "snowflake_id",
                    "",
                )
            ) != discord_id
        ):
            raise ValueError(
                "This Lunar account is already linked "
                "to another Discord account."
            )

        # ----------------------------------------------------
        # METADATA
        # ----------------------------------------------------

        normalized_metadata = {
            str(key): str(value)
            for key, value in (
                metadata or {}
            ).items()
            if value is not None
        }

        if existing:

            existing_metadata = dict(
                getattr(
                    existing,
                    "metadata",
                    None,
                )
                or {}
            )

            existing_metadata.update(
                normalized_metadata
            )

            normalized_metadata = (
                existing_metadata
            )

        # ----------------------------------------------------
        # TIMESTAMPS
        # ----------------------------------------------------

        verified_at = (
            now
            if verified
            else (
                getattr(
                    existing,
                    "verified_at",
                    None,
                )
                if existing
                else None
            )
        )

        created_at = (
            getattr(
                existing,
                "created_at",
                None,
            )
            if existing
            else None
        )

        if created_at is None:
            created_at = now

        # ----------------------------------------------------
        # OLD UUID
        # ----------------------------------------------------

        old_uuid = (
            getattr(
                existing,
                "lunar_uuid",
                None,
            )
            if existing
            else None
        )

        queries: list[
            tuple[str, Sequence[Any]]
        ] = []

        if (
            old_uuid
            and old_uuid != parsed_uuid
        ):

            queries.append(
                (
                    """
                    DELETE FROM account_links_by_uuid
                    WHERE lunar_uuid = ?
                    """,
                    (
                        old_uuid,
                    ),
                )
            )

        # ----------------------------------------------------
        # MAIN ACCOUNT TABLE
        # ----------------------------------------------------

        queries.append(
            (
                """
                INSERT INTO account_links (
                    snowflake_id,
                    lunar_uuid,
                    verification_code,
                    verified,
                    last_message_time,
                    verified_at,
                    created_at,
                    updated_at,
                    metadata
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    discord_id,
                    parsed_uuid,
                    verification_code,
                    verified,
                    last_message_time,
                    verified_at,
                    created_at,
                    now,
                    normalized_metadata,
                ),
            )
        )

        # ----------------------------------------------------
        # UUID LOOKUP TABLE
        # ----------------------------------------------------

        queries.append(
            (
                """
                INSERT INTO account_links_by_uuid (
                    lunar_uuid,
                    snowflake_id,
                    verification_code,
                    verified,
                    last_message_time,
                    verified_at,
                    created_at,
                    updated_at,
                    metadata
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    parsed_uuid,
                    discord_id,
                    verification_code,
                    verified,
                    last_message_time,
                    verified_at,
                    created_at,
                    now,
                    normalized_metadata,
                ),
            )
        )

        await self.db.batch(
            queries,
            logged=True,
        )

        return await self.get(
            discord_id
        )

    async def update_metadata(
        self,
        snowflake_id: int | str,
        metadata: Mapping[str, str],
    ):

        discord_id = str(
            snowflake_id
        )

        existing = await self.get(
            discord_id
        )

        if not existing:
            return None

        existing_metadata = dict(
            getattr(
                existing,
                "metadata",
                None,
            )
            or {}
        )

        existing_metadata.update(
            {
                str(key): str(value)
                for key, value in metadata.items()
                if value is not None
            }
        )

        now = utcnow()

        await self.query(
            """
            UPDATE account_links
            SET
                metadata = ?,
                updated_at = ?
            WHERE snowflake_id = ?
            """,
            (
                existing_metadata,
                now,
                discord_id,
            ),
        )

        lunar_uuid = getattr(
            existing,
            "lunar_uuid",
            None,
        )

        if lunar_uuid:

            await self.query(
                """
                UPDATE account_links_by_uuid
                SET
                    metadata = ?,
                    updated_at = ?
                WHERE lunar_uuid = ?
                """,
                (
                    existing_metadata,
                    now,
                    lunar_uuid,
                ),
            )

        return await self.get(
            discord_id
        )

    async def set_username(
        self,
        snowflake_id: int | str,
        username: str,
    ):

        username = username.strip()

        if not username:
            raise ValueError(
                "Lunar username cannot be empty."
            )

        return await self.update_metadata(
            snowflake_id,
            {
                "username": username,
            },
        )

    async def set_verified(
        self,
        snowflake_id: int | str,
        verified: bool,
    ):

        discord_id = str(
            snowflake_id
        )

        existing = await self.get(
            discord_id
        )

        if not existing:
            return None

        now = utcnow()

        verified_at = (
            now
            if verified
            else None
        )

        await self.query(
            """
            UPDATE account_links
            SET
                verified = ?,
                verified_at = ?,
                updated_at = ?
            WHERE snowflake_id = ?
            """,
            (
                verified,
                verified_at,
                now,
                discord_id,
            ),
        )

        lunar_uuid = getattr(
            existing,
            "lunar_uuid",
            None,
        )

        if lunar_uuid:

            await self.query(
                """
                UPDATE account_links_by_uuid
                SET
                    verified = ?,
                    verified_at = ?,
                    updated_at = ?
                WHERE lunar_uuid = ?
                """,
                (
                    verified,
                    verified_at,
                    now,
                    lunar_uuid,
                ),
            )

        return await self.get(
            discord_id
        )

    async def set_verification_code(
        self,
        snowflake_id: int | str,
        verification_code: str,
    ):

        discord_id = str(
            snowflake_id
        )

        existing = await self.get(
            discord_id
        )

        if not existing:
            return None

        now = utcnow()

        await self.query(
            """
            UPDATE account_links
            SET
                verification_code = ?,
                updated_at = ?
            WHERE snowflake_id = ?
            """,
            (
                verification_code,
                now,
                discord_id,
            ),
        )

        lunar_uuid = getattr(
            existing,
            "lunar_uuid",
            None,
        )

        if lunar_uuid:

            await self.query(
                """
                UPDATE account_links_by_uuid
                SET
                    verification_code = ?,
                    updated_at = ?
                WHERE lunar_uuid = ?
                """,
                (
                    verification_code,
                    now,
                    lunar_uuid,
                ),
            )

        return await self.get(
            discord_id
        )

    async def set_last_message_time(
        self,
        snowflake_id: int | str,
        last_message_time: Optional[
            datetime
        ] = None,
    ):

        discord_id = str(
            snowflake_id
        )

        existing = await self.get(
            discord_id
        )

        if not existing:
            return None

        timestamp = (
            last_message_time
            or utcnow()
        )

        now = utcnow()

        await self.query(
            """
            UPDATE account_links
            SET
                last_message_time = ?,
                updated_at = ?
            WHERE snowflake_id = ?
            """,
            (
                timestamp,
                now,
                discord_id,
            ),
        )

        lunar_uuid = getattr(
            existing,
            "lunar_uuid",
            None,
        )

        if lunar_uuid:

            await self.query(
                """
                UPDATE account_links_by_uuid
                SET
                    last_message_time = ?,
                    updated_at = ?
                WHERE lunar_uuid = ?
                """,
                (
                    timestamp,
                    now,
                    lunar_uuid,
                ),
            )

        return await self.get(
            discord_id
        )

    async def unlink(
        self,
        snowflake_id: int | str,
    ):

        discord_id = str(
            snowflake_id
        )

        existing = await self.get(
            discord_id
        )

        if not existing:
            return False

        lunar_uuid = getattr(
            existing,
            "lunar_uuid",
            None,
        )

        queries = [
            (
                """
                DELETE FROM account_links
                WHERE snowflake_id = ?
                """,
                (
                    discord_id,
                ),
            ),
        ]

        if lunar_uuid:

            queries.append(
                (
                    """
                    DELETE FROM account_links_by_uuid
                    WHERE lunar_uuid = ?
                    """,
                    (
                        lunar_uuid,
                    ),
                )
            )

        await self.db.batch(
            queries,
            logged=True,
        )

        return True

    async def is_verified(
        self,
        snowflake_id: int | str,
    ) -> bool:

        account = await self.get(
            snowflake_id
        )

        if not account:
            return False

        return bool(
            getattr(
                account,
                "verified",
                False,
            )
        )

    async def ensure(
        self,
        snowflake_id: int | str,
        *,
        lunar_uuid: str | uuid.UUID,
        verification_code: str,
        username: Optional[str] = None,
        verified: bool = False,
    ):

        existing = await self.get(
            snowflake_id
        )

        metadata: dict[str, str] = {}

        if existing:

            metadata.update(
                getattr(
                    existing,
                    "metadata",
                    None,
                )
                or {}
            )

        if username:

            metadata["username"] = (
                username.strip()
            )

        if existing:

            existing_uuid = getattr(
                existing,
                "lunar_uuid",
                None,
            )

            if (
                existing_uuid
                and str(existing_uuid)
                != str(lunar_uuid)
            ):

                raise ValueError(
                    "This Discord account is already "
                    "linked to a different Lunar account."
                )

        return await self.link(
            snowflake_id,
            lunar_uuid,
            verification_code,
            verified=verified,
            metadata=metadata,
        )


# ============================================================
# COMMAND STATS
# ============================================================

class CommandStatsRepository(BaseRepository):

    async def increment(
        self,
        command_name: str,
    ) -> None:

        command_name = (
            str(command_name)
            .strip()
            .lower()
        )

        if not command_name:
            return

        # ----------------------------------------------------
        # COUNTER
        # ----------------------------------------------------

        await self.query(
            """
            UPDATE command_counters
            SET uses = uses + 1
            WHERE command_name = ?
            """,
            (
                command_name,
            ),
        )

        # ----------------------------------------------------
        # LAST USED METADATA
        # ----------------------------------------------------

        await self.query(
            """
            INSERT INTO command_usage_meta (
                command_name,
                last_used_at
            )
            VALUES (?, ?)
            """,
            (
                command_name,
                utcnow(),
            ),
        )

    async def get(
        self,
        command_name: str,
    ) -> int:

        command_name = (
            str(command_name)
            .strip()
            .lower()
        )

        if not command_name:
            return 0

        row = await self.one(
            """
            SELECT uses
            FROM command_counters
            WHERE command_name = ?
            """,
            (
                command_name,
            ),
        )

        if not row:
            return 0

        return int(
            row.uses or 0
        )

    async def get_last_used(
        self,
        command_name: str,
    ):

        command_name = (
            str(command_name)
            .strip()
            .lower()
        )

        if not command_name:
            return None

        row = await self.one(
            """
            SELECT last_used_at
            FROM command_usage_meta
            WHERE command_name = ?
            """,
            (
                command_name,
            ),
        )

        if not row:
            return None

        return row.last_used_at

    async def total(self) -> int:

        result = await self.query(
            """
            SELECT uses
            FROM command_counters
            """
        )

        return sum(
            int(row.uses or 0)
            for row in result.all()
        )

    async def all(self):

        result = await self.query(
            """
            SELECT
                command_name,
                uses
            FROM command_counters
            """
        )

        return sorted(
            result.all(),
            key=lambda row: int(
                row.uses or 0
            ),
            reverse=True,
        )


# ============================================================
# XP EVENTS
# ============================================================

class XPRepository(BaseRepository):

    async def record(
        self,
        snowflake_id: int | str,
        *,
        amount: int,
        reason: str,
        guild_id: Optional[int | str],
        channel_id: Optional[int | str],
        balance_after: int,
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ):

        now = utcnow()

        await self.query(
            """
            INSERT INTO xp_events (
                snowflake_id,
                event_date,
                event_id,
                amount,
                reason,
                guild_id,
                channel_id,
                balance_after,
                metadata
            )
            VALUES (
                ?, ?, now(), ?, ?, ?, ?, ?, ?
            )
            """,
            (
                str(snowflake_id),
                now.date(),
                amount,
                reason,
                (
                    str(guild_id)
                    if guild_id is not None
                    else None
                ),
                (
                    str(channel_id)
                    if channel_id is not None
                    else None
                ),
                balance_after,
                dict(metadata or {}),
            ),
        )

    async def recent(
        self,
        snowflake_id: int | str,
        *,
        days: int = 7,
        limit: int = 100,
    ):

        days = max(
            1,
            int(days),
        )

        limit = max(
            1,
            int(limit),
        )

        today = utcnow().date()

        start = today - timedelta(
            days=days
        )

        rows = []

        current = today

        while current >= start:

            result = await self.query(
                """
                SELECT *
                FROM xp_events
                WHERE snowflake_id = ?
                AND event_date = ?
                LIMIT ?
                """,
                (
                    str(snowflake_id),
                    current,
                    limit,
                ),
            )

            rows.extend(
                result.all()
            )

            if len(rows) >= limit:
                break

            current -= timedelta(
                days=1
            )

        return rows[:limit]


# ============================================================
# SHAME EVENTS
# ============================================================

class ShameRepository(BaseRepository):

    async def record(
        self,
        snowflake_id: int | str,
        *,
        amount: int,
        reason: str,
        moderator_id: Optional[int | str],
        guild_id: Optional[int | str],
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ):

        now = utcnow()

        await self.query(
            """
            INSERT INTO shame_events (
                snowflake_id,
                event_date,
                event_id,
                amount,
                reason,
                moderator_id,
                guild_id,
                metadata
            )
            VALUES (
                ?, ?, now(), ?, ?, ?, ?, ?
            )
            """,
            (
                str(snowflake_id),
                now.date(),
                amount,
                reason,
                (
                    str(moderator_id)
                    if moderator_id is not None
                    else None
                ),
                (
                    str(guild_id)
                    if guild_id is not None
                    else None
                ),
                dict(metadata or {}),
            ),
        )


# ============================================================
# GUILDS
# ============================================================

class GuildRepository(BaseRepository):

    async def ensure(
        self,
        guild_id: int | str,
        *,
        name: Optional[str] = None,
    ):

        guild_id = str(
            guild_id
        )

        existing = await self.one(
            """
            SELECT *
            FROM guilds
            WHERE guild_id = ?
            """,
            (
                guild_id,
            ),
        )

        if existing:
            return existing

        now = utcnow()

        await self.query(
            """
            INSERT INTO guilds (
                guild_id,
                name,
                enabled,
                prefix,
                log_channel_id,
                welcome_channel_id,
                created_at,
                updated_at,
                metadata
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                guild_id,
                name,
                True,
                "!",
                None,
                None,
                now,
                now,
                {},
            ),
        )

        return await self.one(
            """
            SELECT *
            FROM guilds
            WHERE guild_id = ?
            """,
            (
                guild_id,
            ),
        )

    async def update(
        self,
        guild_id: int | str,
        **fields,
    ):

        allowed = {
            "name",
            "enabled",
            "prefix",
            "log_channel_id",
            "welcome_channel_id",
            "metadata",
        }

        updates = []
        values = []

        for key, value in fields.items():

            if key not in allowed:
                continue

            updates.append(
                f"{key} = ?"
            )

            values.append(value)

        if not updates:
            return

        updates.append(
            "updated_at = ?"
        )

        values.append(
            utcnow()
        )

        values.append(
            str(guild_id)
        )

        await self.query(
            f"""
            UPDATE guilds
            SET {", ".join(updates)}
            WHERE guild_id = ?
            """,
            values,
        )


# ============================================================
# SETTINGS
# ============================================================

class SettingsRepository(BaseRepository):

    async def set(
        self,
        scope: str,
        scope_id: int | str,
        setting: str,
        value: Any,
    ):

        await self.query(
            """
            INSERT INTO settings (
                scope,
                scope_id,
                setting,
                value,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(scope),
                str(scope_id),
                str(setting),
                json_dumps(value),
                utcnow(),
            ),
        )

    async def get(
        self,
        scope: str,
        scope_id: int | str,
        setting: str,
        default: Any = None,
    ):

        row = await self.one(
            """
            SELECT value
            FROM settings
            WHERE scope = ?
            AND scope_id = ?
            AND setting = ?
            """,
            (
                str(scope),
                str(scope_id),
                str(setting),
            ),
        )

        if not row:
            return default

        return json_loads(
            row.value,
            default,
        )


# ============================================================
# FEATURE FLAGS
# ============================================================

class FeatureFlagRepository(BaseRepository):

    async def set(
        self,
        scope: str,
        scope_id: int | str,
        feature: str,
        enabled: bool,
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ):

        await self.query(
            """
            INSERT INTO feature_flags (
                scope,
                scope_id,
                feature,
                enabled,
                updated_at,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(scope),
                str(scope_id),
                str(feature),
                enabled,
                utcnow(),
                dict(metadata or {}),
            ),
        )

    async def enabled(
        self,
        scope: str,
        scope_id: int | str,
        feature: str,
        default: bool = False,
    ) -> bool:

        row = await self.one(
            """
            SELECT enabled
            FROM feature_flags
            WHERE scope = ?
            AND scope_id = ?
            AND feature = ?
            """,
            (
                str(scope),
                str(scope_id),
                str(feature),
            ),
        )

        if not row:
            return default

        return bool(
            row.enabled
        )


# ============================================================
# COOLDOWNS
# ============================================================

class CooldownRepository(BaseRepository):

    async def set(
        self,
        scope: str,
        scope_id: int | str,
        command: str,
        expires_at: datetime,
    ):

        await self.query(
            """
            INSERT INTO cooldowns (
                scope,
                scope_id,
                command,
                expires_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                str(scope),
                str(scope_id),
                str(command),
                expires_at,
            ),
        )

    async def get(
        self,
        scope: str,
        scope_id: int | str,
        command: str,
    ):

        return await self.one(
            """
            SELECT expires_at
            FROM cooldowns
            WHERE scope = ?
            AND scope_id = ?
            AND command = ?
            """,
            (
                str(scope),
                str(scope_id),
                str(command),
            ),
        )

    async def active(
        self,
        scope: str,
        scope_id: int | str,
        command: str,
    ) -> bool:

        row = await self.get(
            scope,
            scope_id,
            command,
        )

        if not row:
            return False

        expires_at = row.expires_at

        if expires_at is None:
            return False

        return expires_at > utcnow()


# ============================================================
# AUDIT LOG
# ============================================================

class AuditRepository(BaseRepository):

    async def record(
        self,
        guild_id: int | str,
        *,
        actor_id: Optional[int | str],
        action: str,
        target_id: Optional[int | str],
        reason: Optional[str] = None,
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ):

        now = utcnow()

        await self.query(
            """
            INSERT INTO audit_logs (
                guild_id,
                event_date,
                event_id,
                actor_id,
                action,
                target_id,
                reason,
                metadata
            )
            VALUES (
                ?, ?, now(), ?, ?, ?, ?, ?
            )
            """,
            (
                str(guild_id),
                now.date(),
                (
                    str(actor_id)
                    if actor_id is not None
                    else None
                ),
                action,
                (
                    str(target_id)
                    if target_id is not None
                    else None
                ),
                reason,
                dict(metadata or {}),
            ),
        )


# ============================================================
# GLOBAL COUNTERS / STATS
# ============================================================

class StatsRepository(BaseRepository):

    async def increment(
        self,
        stat_name: str,
        amount: int = 1,
    ):

        stat_name = (
            str(stat_name)
            .strip()
        )

        if not stat_name:
            return

        await self.query(
            """
            UPDATE bot_counters
            SET value = value + ?
            WHERE stat_name = ?
            """,
            (
                amount,
                stat_name,
            ),
        )

    async def get(
        self,
        stat_name: str,
    ) -> int:

        row = await self.one(
            """
            SELECT value
            FROM bot_counters
            WHERE stat_name = ?
            """,
            (
                str(stat_name),
            ),
        )

        if not row:
            return 0

        return int(
            row.value or 0
        )


# ============================================================
# GITHUB
# ============================================================

class GitHubRepository(BaseRepository):

    async def register_repository(
        self,
        repository: str,
        *,
        url: str,
        owner: str,
        name: str,
        branch: str,
        channel_id: int | str,
        enabled: bool = True,
    ):

        await self.query(
            """
            INSERT INTO github_repositories (
                repository,
                url,
                owner,
                name,
                branch,
                channel_id,
                enabled,
                last_commit_sha,
                last_checked_at,
                metadata
            )
            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            (
                repository,
                url,
                owner,
                name,
                branch,
                str(channel_id),
                enabled,
                None,
                None,
                {},
            ),
        )

    async def get(
        self,
        repository: str,
    ):

        return await self.one(
            """
            SELECT *
            FROM github_repositories
            WHERE repository = ?
            """,
            (
                repository,
            ),
        )

    async def set_last_commit(
        self,
        repository: str,
        sha: str,
    ):

        await self.query(
            """
            UPDATE github_repositories
            SET
                last_commit_sha = ?,
                last_checked_at = ?
            WHERE repository = ?
            """,
            (
                sha,
                utcnow(),
                repository,
            ),
        )

    async def record_commit(
        self,
        repository: str,
        *,
        committed_at: datetime,
        sha: str,
        author: str,
        committer: str,
        message: str,
        branch: str,
        verified: bool,
        additions: int,
        deletions: int,
        changed_files: int,
        html_url: str,
        files: Sequence[str],
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ):

        await self.query(
            """
            INSERT INTO github_commits (
                repository,
                committed_date,
                committed_at,
                sha,
                author,
                committer,
                message,
                branch,
                verified,
                additions,
                deletions,
                changed_files,
                html_url,
                files,
                metadata
            )
            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?
            )
            """,
            (
                repository,
                committed_at.date(),
                committed_at,
                sha,
                author,
                committer,
                message,
                branch,
                verified,
                additions,
                deletions,
                changed_files,
                html_url,
                list(files),
                dict(metadata or {}),
            ),
        )

    async def recent_commits(
        self,
        repository: str,
        committed_date,
        limit: int = 25,
    ):

        result = await self.query(
            """
            SELECT *
            FROM github_commits
            WHERE repository = ?
            AND committed_date = ?
            LIMIT ?
            """,
            (
                repository,
                committed_date,
                limit,
            ),
        )

        return result.all()

    async def record_issue(
        self,
        repository: str,
        *,
        issue_number: int,
        title: str,
        body: str,
        author_id: int | str,
        html_url: str,
        state: str = "open",
        issue_type: str = "suggestion",
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ):

        await self.query(
            """
            INSERT INTO github_issues (
                repository,
                issue_number,
                title,
                body,
                author_id,
                html_url,
                state,
                issue_type,
                created_at,
                metadata
            )
            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            (
                repository,
                issue_number,
                title,
                body,
                str(author_id),
                html_url,
                state,
                issue_type,
                utcnow(),
                dict(metadata or {}),
            ),
        )

    async def get_issue(
        self,
        repository: str,
        issue_number: int,
    ):

        return await self.one(
            """
            SELECT *
            FROM github_issues
            WHERE repository = ?
            AND issue_number = ?
            """,
            (
                repository,
                issue_number,
            ),
        )

    async def recent_issues(
        self,
        repository: str,
        limit: int = 25,
    ):

        result = await self.query(
            """
            SELECT *
            FROM github_issues
            WHERE repository = ?
            LIMIT ?
            """,
            (
                repository,
                limit,
            ),
        )

        return result.all()


# ============================================================
# EXTENSION STORAGE
# ============================================================

class ExtensionRepository(BaseRepository):
    """
    Generic storage layer.

    Useful for temporary or experimental state before a
    dedicated query-oriented table is created.
    """

    async def set(
        self,
        namespace: str,
        entity_id: int | str,
        key: str,
        value: Any,
        *,
        expires_at: Optional[
            datetime
        ] = None,
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ):

        await self.query(
            """
            INSERT INTO extension_data (
                namespace,
                entity_id,
                key,
                value,
                updated_at,
                expires_at,
                metadata
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                str(namespace),
                str(entity_id),
                str(key),
                json_dumps(value),
                utcnow(),
                expires_at,
                dict(metadata or {}),
            ),
        )

    async def get(
        self,
        namespace: str,
        entity_id: int | str,
        key: str,
        default: Any = None,
    ):

        row = await self.one(
            """
            SELECT value
            FROM extension_data
            WHERE namespace = ?
            AND entity_id = ?
            AND key = ?
            """,
            (
                str(namespace),
                str(entity_id),
                str(key),
            ),
        )

        if not row:
            return default

        return json_loads(
            row.value,
            default,
        )

    async def delete(
        self,
        namespace: str,
        entity_id: int | str,
        key: str,
    ) -> bool:

        existing = await self.get(
            namespace,
            entity_id,
            key,
            default=None,
        )

        if existing is None:
            return False

        await self.query(
            """
            DELETE FROM extension_data
            WHERE namespace = ?
            AND entity_id = ?
            AND key = ?
            """,
            (
                str(namespace),
                str(entity_id),
                str(key),
            ),
        )

        return True


# ============================================================
# MENTIONS
# ============================================================

class MentionRepository(BaseRepository):

    async def create(
        self,
        *,
        mentioned_id: int | str,
        message_id: int | str,
        message_author_id: int | str,
        channel_id: int | str,
        guild_id: int | str,
        created_at: Optional[
            datetime
        ] = None,
    ) -> None:

        await self.query(
            """
            INSERT INTO mentions_by_user (
                mentioned_id,
                archived,
                is_read,
                created_at,
                id,
                message_id,
                message_author_id,
                channel_id,
                guild_id
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                str(mentioned_id),
                False,
                False,
                created_at or utcnow(),
                uuid.uuid4(),
                str(message_id),
                str(message_author_id),
                str(channel_id),
                str(guild_id),
            ),
        )

    async def unread(
        self,
        mentioned_id: int | str,
        *,
        limit: int = 10,
    ):

        return await self.query(
            """
            SELECT *
            FROM mentions_by_user
            WHERE mentioned_id = ?
            AND archived = false
            AND is_read = false
            LIMIT ?
            """,
            (
                str(mentioned_id),
                max(
                    1,
                    int(limit),
                ),
            ),
        )

    async def mark_read(
        self,
        row,
    ) -> None:

        await self.query(
            """
            INSERT INTO mentions_by_user (
                mentioned_id,
                archived,
                is_read,
                created_at,
                id,
                message_id,
                message_author_id,
                channel_id,
                guild_id
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                row.mentioned_id,
                bool(row.archived),
                True,
                row.created_at,
                row.id,
                row.message_id,
                row.message_author_id,
                row.channel_id,
                row.guild_id,
            ),
        )

        await self.query(
            """
            DELETE FROM mentions_by_user
            WHERE mentioned_id = ?
            AND archived = ?
            AND is_read = ?
            AND created_at = ?
            AND id = ?
            """,
            (
                row.mentioned_id,
                bool(row.archived),
                False,
                row.created_at,
                row.id,
            ),
        )

    async def mark_all_read(
        self,
        mentioned_id: int | str,
    ) -> None:

        while True:

            result = await self.unread(
                mentioned_id,
                limit=100,
            )

            rows = result.all()

            if not rows:
                break

            for row in rows:
                await self.mark_read(row)

            if len(rows) < 100:
                break

    async def archive_all(
        self,
        mentioned_id: int | str,
    ) -> None:

        while True:

            result = await self.unread(
                mentioned_id,
                limit=100,
            )

            rows = result.all()

            if not rows:
                break

            for row in rows:

                await self.query(
                    """
                    INSERT INTO mentions_by_user (
                        mentioned_id,
                        archived,
                        is_read,
                        created_at,
                        id,
                        message_id,
                        message_author_id,
                        channel_id,
                        guild_id
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        row.mentioned_id,
                        True,
                        bool(row.is_read),
                        row.created_at,
                        row.id,
                        row.message_id,
                        row.message_author_id,
                        row.channel_id,
                        row.guild_id,
                    ),
                )

                await self.query(
                    """
                    DELETE FROM mentions_by_user
                    WHERE mentioned_id = ?
                    AND archived = ?
                    AND is_read = ?
                    AND created_at = ?
                    AND id = ?
                    """,
                    (
                        row.mentioned_id,
                        bool(row.archived),
                        bool(row.is_read),
                        row.created_at,
                        row.id,
                    ),
                )

            if len(rows) < 100:
                break


# ============================================================
# VARIABLES
# ============================================================

class VariableRepository(BaseRepository):

    async def get(
        self,
        identifier: str,
    ):

        return await self.one(
            """
            SELECT
                identifier,
                int_value,
                string_value,
                metadata
            FROM variables
            WHERE identifier = ?
            """,
            (
                str(identifier),
            ),
        )

    async def set(
        self,
        identifier: str,
        *,
        int_value: int | None = None,
        string_value: str | None = None,
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ) -> None:

        await self.query(
            """
            INSERT INTO variables (
                identifier,
                int_value,
                string_value,
                metadata
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                str(identifier),
                int_value,
                string_value,
                dict(metadata or {}),
            ),
        )

    async def update(
        self,
        identifier: str,
        *,
        int_value: int | None = None,
        string_value: str | None = None,
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ) -> None:

        await self.query(
            """
            UPDATE variables
            SET
                int_value = ?,
                string_value = ?,
                metadata = ?
            WHERE identifier = ?
            """,
            (
                int_value,
                string_value,
                dict(metadata or {}),
                str(identifier),
            ),
        )

    async def ensure(
        self,
        identifier: str,
        *,
        int_value: int | None = None,
        string_value: str | None = None,
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ) -> None:

        existing = await self.get(
            identifier
        )

        if existing is not None:
            return

        await self.set(
            identifier,
            int_value=int_value,
            string_value=string_value,
            metadata=metadata,
        )

    async def get_int(
        self,
        identifier: str,
        default: int = 0,
    ) -> int:

        row = await self.get(
            identifier
        )

        if (
            row is None
            or row.int_value is None
        ):
            return default

        return int(
            row.int_value
        )

    # ========================================================
    # MAINTENANCE
    # ========================================================

    async def set_maintenance(
        self,
        enabled: bool,
        *,
        reason: str = "",
        changed_by: int | str | None = None,
    ) -> None:

        metadata = {
            "changed_at": (
                utcnow().isoformat()
            ),
        }

        if changed_by is not None:

            metadata["changed_by"] = (
                str(changed_by)
            )

        await self.set(
            "bot_maintenance",
            int_value=(
                1
                if enabled
                else 0
            ),
            string_value=reason.strip(),
            metadata=metadata,
        )

    async def get_maintenance(
        self,
    ) -> dict[str, Any]:

        row = await self.get(
            "bot_maintenance"
        )

        if row is None:

            return {
                "enabled": False,
                "reason": "",
                "metadata": {},
            }

        return {
            "enabled": bool(
                row.int_value or 0
            ),
            "reason": (
                row.string_value or ""
            ),
            "metadata": dict(
                row.metadata or {}
            ),
        }


# ============================================================
# GIVEAWAYS
# ============================================================

class GiveawayRepository(BaseRepository):

    async def create(
        self,
        *,
        giveaway_id: str,
        message_id: int | str,
        channel_id: int | str,
        guild_id: int | str,
        host_id: int | str,
        duration_seconds: int,
        prize: str,
        description: str,
        winners_count: int,
        created_at: datetime,
        ends_at: datetime,
        metadata: Optional[
            Mapping[str, str]
        ] = None,
    ):

        await self.query(
            """
            INSERT INTO giveaways (
                giveaway_id,
                message_id,
                channel_id,
                guild_id,
                host_id,
                duration_seconds,
                prize,
                description,
                winners_count,
                participant_ids,
                winner_ids,
                state,
                created_at,
                ends_at,
                ended_at,
                metadata
            )
            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            (
                giveaway_id,
                str(message_id),
                str(channel_id),
                str(guild_id),
                str(host_id),
                duration_seconds,
                prize,
                description,
                winners_count,
                set(),
                set(),
                "active",
                created_at,
                ends_at,
                None,
                dict(metadata or {}),
            ),
        )

        bucket = ends_at.strftime(
            "%Y%m%d%H"
        )

        await self.query(
            """
            INSERT INTO giveaways_active (
                bucket,
                ends_at,
                giveaway_id
            )
            VALUES (?, ?, ?)
            """,
            (
                bucket,
                ends_at,
                giveaway_id,
            ),
        )

        await self.query(
            """
            INSERT INTO giveaways_by_message (
                message_id,
                giveaway_id
            )
            VALUES (?, ?)
            """,
            (
                str(message_id),
                giveaway_id,
            ),
        )

    async def get(
        self,
        giveaway_id: str,
    ):

        return await self.one(
            """
            SELECT *
            FROM giveaways
            WHERE giveaway_id = ?
            """,
            (
                giveaway_id,
            ),
        )

    async def get_by_message(
        self,
        message_id: int | str,
    ):

        mapping = await self.one(
            """
            SELECT giveaway_id
            FROM giveaways_by_message
            WHERE message_id = ?
            """,
            (
                str(message_id),
            ),
        )

        if not mapping:
            return None

        return await self.get(
            mapping.giveaway_id
        )

    async def add_entry(
        self,
        giveaway_id: str,
        user_id: int | str,
    ):

        await self.query(
            """
            UPDATE giveaways
            SET participant_ids =
                participant_ids + ?
            WHERE giveaway_id = ?
            """,
            (
                {
                    str(user_id)
                },
                giveaway_id,
            ),
        )

    async def remove_entry(
        self,
        giveaway_id: str,
        user_id: int | str,
    ):

        await self.query(
            """
            UPDATE giveaways
            SET participant_ids =
                participant_ids - ?
            WHERE giveaway_id = ?
            """,
            (
                {
                    str(user_id)
                },
                giveaway_id,
            ),
        )

    async def clear_winners(
        self,
        giveaway_id: str,
    ) -> None:

        await self.query(
            """
            UPDATE giveaways
            SET winner_ids = ?
            WHERE giveaway_id = ?
            """,
            (
                set(),
                giveaway_id,
            ),
        )

    async def set_winners(
        self,
        giveaway_id: str,
        winners: set[str],
    ) -> None:

        normalized = {
            str(user_id)
            for user_id in winners
        }

        await self.query(
            """
            UPDATE giveaways
            SET winner_ids = ?
            WHERE giveaway_id = ?
            """,
            (
                normalized,
                giveaway_id,
            ),
        )

    async def replace_winners(
        self,
        giveaway_id: str,
        winners: set[str],
    ) -> None:

        await self.set_winners(
            giveaway_id,
            winners,
        )

    async def update_metadata(
        self,
        giveaway_id: str,
        metadata: Mapping[str, str],
    ):

        giveaway = await self.get(
            giveaway_id
        )

        if not giveaway:
            return None

        existing_metadata = dict(
            getattr(
                giveaway,
                "metadata",
                None,
            )
            or {}
        )

        existing_metadata.update(
            {
                str(key): str(value)
                for key, value in metadata.items()
                if value is not None
            }
        )

        await self.query(
            """
            UPDATE giveaways
            SET metadata = ?
            WHERE giveaway_id = ?
            """,
            (
                existing_metadata,
                giveaway_id,
            ),
        )

        return await self.get(
            giveaway_id
        )

    async def end(
        self,
        giveaway_id: str,
        *,
        winners: set[str],
        ended_at: datetime,
    ):

        giveaway = await self.get(
            giveaway_id
        )

        if not giveaway:
            return None

        normalized_winners = {
            str(user_id)
            for user_id in winners
        }

        await self.query(
            """
            UPDATE giveaways
            SET
                state = ?,
                winner_ids = ?,
                ended_at = ?
            WHERE giveaway_id = ?
            """,
            (
                "ended",
                normalized_winners,
                ended_at,
                giveaway_id,
            ),
        )

        bucket = giveaway.ends_at.strftime(
            "%Y%m%d%H"
        )

        await self.query(
            """
            DELETE FROM giveaways_active
            WHERE bucket = ?
            AND ends_at = ?
            AND giveaway_id = ?
            """,
            (
                bucket,
                giveaway.ends_at,
                giveaway_id,
            ),
        )

        return await self.get(
            giveaway_id
        )

    async def delete(
        self,
        giveaway_id: str,
    ):

        giveaway = await self.get(
            giveaway_id
        )

        if not giveaway:
            return None

        await self.query(
            """
            DELETE FROM giveaways
            WHERE giveaway_id = ?
            """,
            (
                giveaway_id,
            ),
        )

        await self.query(
            """
            DELETE FROM giveaways_by_message
            WHERE message_id = ?
            """,
            (
                giveaway.message_id,
            ),
        )

        if giveaway.state == "active":

            bucket = giveaway.ends_at.strftime(
                "%Y%m%d%H"
            )

            await self.query(
                """
                DELETE FROM giveaways_active
                WHERE bucket = ?
                AND ends_at = ?
                AND giveaway_id = ?
                """,
                (
                    bucket,
                    giveaway.ends_at,
                    giveaway_id,
                ),
            )

        return giveaway

    async def due(
        self,
        *,
        now: Optional[datetime] = None,
        limit: int = 50,
        hours: int = 24,
    ):

        now = now or utcnow()

        limit = max(
            1,
            int(limit),
        )

        hours = max(
            1,
            int(hours),
        )

        buckets = set()

        for offset in range(
            hours
        ):

            timestamp = (
                now
                - timedelta(
                    hours=offset
                )
            )

            buckets.add(
                timestamp.strftime(
                    "%Y%m%d%H"
                )
            )

        rows = []

        for bucket in sorted(
            buckets,
        ):

            result = await self.query(
                """
                SELECT giveaway_id
                FROM giveaways_active
                WHERE bucket = ?
                AND ends_at <= ?
                LIMIT ?
                """,
                (
                    bucket,
                    now,
                    limit,
                ),
            )

            rows.extend(
                result.all()
            )

            if len(rows) >= limit:
                break

        # ----------------------------------------------------
        # DEDUPLICATE
        # ----------------------------------------------------

        seen = set()
        giveaway_ids = []

        for row in rows:

            giveaway_id = (
                row.giveaway_id
            )

            if giveaway_id in seen:
                continue

            seen.add(
                giveaway_id
            )

            giveaway_ids.append(
                giveaway_id
            )

            if len(giveaway_ids) >= limit:
                break

        giveaways = []

        for giveaway_id in giveaway_ids:

            giveaway = await self.get(
                giveaway_id
            )

            if (
                giveaway
                and giveaway.state == "active"
                and giveaway.ends_at <= now
            ):
                giveaways.append(
                    giveaway
                )

        return giveaways


# ============================================================
# CSV MIGRATION
# ============================================================

class CSVImporter:

    def __init__(
        self,
        database: ScyllaDatabase,
    ):
        self.db = database

    # ========================================================
    # USERS CSV
    # ========================================================

    async def import_users(
        self,
        rows: Iterable[
            Mapping[str, str]
        ],
    ) -> int:

        imported = 0

        if self.db.users is None:
            raise RuntimeError(
                "Database is not initialized."
            )

        for row in rows:

            snowflake_id = (
                row.get(
                    "snowflakeid"
                )
            )

            if not snowflake_id:
                continue

            def integer(
                key: str,
                default: int = 0,
            ) -> int:

                raw = row.get(key)

                if raw in (
                    None,
                    "",
                ):
                    return default

                try:
                    return int(raw)

                except (
                    TypeError,
                    ValueError,
                ):
                    return default

            existing = await self.db.users.get(
                snowflake_id
            )

            if existing:

                await self.db.users.update(
                    snowflake_id,

                    level=integer(
                        "level",
                        1,
                    ),

                    required_xp=integer(
                        "required_xp",
                        100,
                    ),

                    xp=integer(
                        "xp",
                        0,
                    ),

                    shame_points=integer(
                        "shame_points",
                        0,
                    ),

                    metadata={
                        "migration":
                        "users_lunar.csv"
                    },
                )

            else:

                await self.db.users.create(
                    snowflake_id,

                    level=integer(
                        "level",
                        1,
                    ),

                    required_xp=integer(
                        "required_xp",
                        100,
                    ),

                    xp=integer(
                        "xp",
                        0,
                    ),

                    shame_points=integer(
                        "shame_points",
                        0,
                    ),

                    metadata={
                        "migration":
                        "users_lunar.csv"
                    },
                )

            imported += 1

        return imported

    # ========================================================
    # ACCOUNT LINKS CSV
    # ========================================================

    async def import_account_links(
        self,
        rows: Iterable[
            Mapping[str, str]
        ],
    ) -> int:

        imported = 0

        if self.db.account_links is None:
            raise RuntimeError(
                "Database is not initialized."
            )

        for row in rows:

            snowflake_id = (
                row.get(
                    "snowflakeid"
                )
            )

            lunar_uuid = (
                row.get(
                    "lunaruuid"
                )
            )

            verification_code = (
                row.get(
                    "verification_code"
                )
            )

            if not all(
                (
                    snowflake_id,
                    lunar_uuid,
                    verification_code,
                )
            ):
                continue

            raw_verified = str(
                row.get(
                    "verified",
                    "False",
                )
            ).strip().lower()

            verified = (
                raw_verified
                in {
                    "true",
                    "1",
                    "yes",
                    "y",
                }
            )

            last_message_time = None

            raw_time = row.get(
                "last_message_time"
            )

            if raw_time:

                try:

                    last_message_time = (
                        datetime.strptime(
                            raw_time,
                            "%Y-%m-%d %H:%M:%S.%f%z",
                        )
                    )

                except ValueError:

                    try:

                        last_message_time = (
                            datetime.fromisoformat(
                                raw_time
                            )
                        )

                    except ValueError:

                        log.warning(
                            "Could not parse "
                            "last_message_time "
                            "for %s",
                            snowflake_id,
                        )

            await self.db.account_links.link(
                snowflake_id,
                lunar_uuid,
                verification_code,
                verified=verified,
                last_message_time=(
                    last_message_time
                ),
            )

            imported += 1

        return imported


# ============================================================
# GLOBAL DATABASE
# ============================================================

db = ScyllaDatabase(
    SCYLLA_CONFIG
)


# ============================================================
# STARTUP HELPERS
# ============================================================

async def initialize_database():
    await db.initialize()

    return db


async def close_database():
    await db.close()


# ============================================================
# CSV CONVENIENCE
# ============================================================

async def import_csv_data(
    users_rows: Optional[
        Iterable[
            Mapping[str, str]
        ]
    ] = None,
    account_rows: Optional[
        Iterable[
            Mapping[str, str]
        ]
    ] = None,
):

    importer = CSVImporter(
        db
    )

    users_count = 0
    account_count = 0

    if users_rows is not None:

        users_count = (
            await importer.import_users(
                users_rows
            )
        )

    if account_rows is not None:

        account_count = (
            await importer.import_account_links(
                account_rows
            )
        )

    return {
        "users": users_count,
        "account_links": account_count,
    }


# ============================================================
# DATABASE EXTENSION GUIDE
# ============================================================
#
# When adding a NEW large system:
#
# 1. Create a dedicated table in CORE_SCHEMA.
#
# 2. Create a repository class.
#
# 3. Add the repository attribute inside
#    ScyllaDatabase.__init__().
#
# 4. Bind it inside _bind_repositories().
#
# Example:
#
# class EconomyRepository(BaseRepository):
#
#     async def get_balance(
#         self,
#         user_id: int | str,
#     ):
#         ...
#
#     async def add_coins(
#         self,
#         user_id: int | str,
#         amount: int,
#     ):
#         ...
#
# ============================================================
# FUTURE MODULES
# ============================================================
#
# Economy
# -------
# balances
# transactions
# daily rewards
# shops
# purchases
# trading
#
# Gacha
# -----
# cards
# owned cards
# pulls
# banners
# pity
# inventory
# teams
# battle history
#
# Library
# -------
# manga
# manhwa
# manhua
# novels
# reading progress
# bookmarks
# favorites
# history
#
# AniList
# -------
# accounts
# cached titles
# sync state
# activity
# notifications
#
# Moderation
# ----------
# warnings
# punishments
# mutes
# bans
# kicks
# appeals
# moderator actions
#
# Requests
# --------
# manga requests
# novel requests
# approvals
# denials
# request history
#
# Tickets
# -------
# ticket metadata
# messages
# staff actions
# closures
#
# Reminders
# ---------
# scheduled events
# recurring events
# delivery state
#
# Achievements
# ------------
# definitions
# user progress
# unlock history
#
# Leaderboards
# ------------
# XP
# coins
# chapters
# anime
# messages
# gacha
#
# GitHub
# ------
# repositories
# commits
# releases
# issues
# pull requests
# deployment history
#
# ============================================================
# IMPORTANT SCYLLA MODELING RULE
# ============================================================
#
# Do not create arbitrary secondary indexes for new access
# patterns.
#
# Model tables around the queries you actually need.
#
# Example:
#
# Need:
#
#     Find account by Lunar UUID
#
# Use:
#
#     account_links_by_uuid
#
# rather than:
#
#     SELECT ... WHERE lunar_uuid = ?
#
# This keeps the data model query-oriented and scalable.
#
# ===========================================================

