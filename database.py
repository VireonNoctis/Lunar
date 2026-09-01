
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
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


def json_loads(value: Any, default: Any = None) -> Any:
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
# CONFIG
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
    # AUDIT
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
    # GENERIC EXTENSION STORAGE
    # ========================================================
    #
    # This table is intentionally generic.
    #
    # It is NOT meant to replace proper query-oriented tables.
    # It is useful for:
    #
    #   - temporary metadata
    #   - experimental systems
    #   - caches
    #   - plugin state
    #   - future features
    #
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

        # ====================================================
        # EXTENSION AREA
        # ====================================================
        #
        # Add future repositories here.
        #
        # self.economy = None
        # self.inventory = None
        # self.gacha = None
        # self.library = None
        # self.anilist = None
        # self.novels = None
        # self.manga = None
        # self.requests = None
        # self.tickets = None
        # self.reminders = None
        # self.moderation = None
        # self.warnings = None
        # self.roles = None
        # self.achievements = None
        # self.leaderboards = None
        # self.statistics = None
        #
        # ====================================================

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
                auth_provider = (
                    PlainTextAuthProvider(
                        username=self.config.username,
                        password=self.config.password,
                    )
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
                f"'replication_factor': "
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

        self.xp = XPRepository(self)

        self.shame = ShameRepository(self)

        self.guilds = GuildRepository(self)

        self.settings = SettingsRepository(
            self
        )

        self.flags = FeatureFlagRepository(
            self
        )

        self.cooldowns = CooldownRepository(
            self
        )

        self.audit = AuditRepository(
            self
        )

        self.stats = StatsRepository(
            self
        )

        self.github = GitHubRepository(
            self
        )

        self.extensions = ExtensionRepository(
            self
        )

        # ====================================================
        # EXTENSION AREA
        # ====================================================
        #
        # Add:
        #
        # self.economy = EconomyRepository(self)
        #
        # self.gacha = GachaRepository(self)
        #
        # self.library = LibraryRepository(self)
        #
        # self.anilist = AniListRepository(self)
        #
        # ====================================================

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

        response = await asyncio.to_thread(
            self.session.execute,
            statement,
            parameters or (),
            timeout=self.config.request_timeout,
        )

        return response

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

        if consistency:
            statement.consistency_level = consistency

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
                "SELECT release_version "
                "FROM system.local"
            )

            return result.one() is not None

        except Exception as error:

            log.error(
                "Scylla health check failed: %s",
                error,
            )

            return False

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

    # ========================================================
    # GENERIC HELPERS
    # ========================================================

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
                {},
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

        while new_xp >= required_xp:

            new_xp -= required_xp

            level += 1

            required_xp = int(
                required_xp * 1.15
            )

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
                utcnow(),
                utcnow(),
                str(snowflake_id),
            ),
        )

        # Also store an XP event.

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
        #
        # This query intentionally isn't used as the primary lookup
        # because ScyllaDB favors queries designed around partition keys.
        #
        # If this becomes common, create a dedicated
        # account_links_by_uuid table.
        #
        raise NotImplementedError(
            "Create an account_links_by_uuid table "
            "for this access pattern."
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
    ):

        now = utcnow()

        await self.query(
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(snowflake_id),
                uuid.UUID(str(lunar_uuid)),
                verification_code,
                verified,
                last_message_time,
                now if verified else None,
                now,
                now,
                {},
            ),
        )

    async def set_verified(
        self,
        snowflake_id: int | str,
        verified: bool,
    ):

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
                utcnow() if verified else None,
                utcnow(),
                str(snowflake_id),
            ),
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
            VALUES (?, ?, now(), ?, ?, ?, ?, ?, ?)
            """,
            (
                str(snowflake_id),
                now.date(),
                amount,
                reason,
                str(guild_id)
                if guild_id is not None
                else None,
                str(channel_id)
                if channel_id is not None
                else None,
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

        today = utcnow().date()

        start = today.fromordinal(
            max(
                1,
                today.toordinal() - days
            )
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

            current = current.fromordinal(
                current.toordinal() - 1
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
            VALUES (?, ?, now(), ?, ?, ?, ?, ?)
            """,
            (
                str(snowflake_id),
                now.date(),
                amount,
                reason,
                str(moderator_id)
                if moderator_id is not None
                else None,
                str(guild_id)
                if guild_id is not None
                else None,
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

        guild_id = str(guild_id)

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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                scope,
                str(scope_id),
                setting,
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
                scope,
                str(scope_id),
                setting,
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
                scope,
                str(scope_id),
                feature,
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
                scope,
                str(scope_id),
                feature,
            ),
        )

        if not row:
            return default

        return bool(row.enabled)


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
                scope,
                str(scope_id),
                command,
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
                scope,
                str(scope_id),
                command,
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

        return (
            row.expires_at
            and row.expires_at > utcnow()
        )


# ============================================================
# AUDIT LOG
# ============================================================

class AuditRepository(BaseRepository):

    async def record(
        self,
        guild_id: int | str,
        *,
       