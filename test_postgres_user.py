import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def test():
    url = os.environ.get('SUPABASE_AVA_MEMORY_URL')
    if not url:
        print('ERROR: URL not found')
        return
    
    # Pooler format requires user.project_id
    url_postgres = url.replace('ava_analytics.qzyydcfvjotfhylithhl:Azfreshart12', 'postgres.qzyydcfvjotfhylithhl:Azfreshart12')
    
    print('[test] Trying postgres user with project ID (pooler format)...')
    print(f'URL: {url_postgres}')
    try:
        conn = await asyncpg.connect(url_postgres, statement_cache_size=0, timeout=5)
        row = await conn.fetchrow('SELECT current_user AS user')
        print(f'✓ Connected as: {row["user"]}')
        
        # Check if tables exist
        tables = await conn.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        print(f'✓ Tables in public schema: {len(tables)}')
        for t in tables:
            print(f'  - {t["table_name"]}')
        
        await conn.close()
        print('\n[SUCCESS] Connection verified!')
    except Exception as e:
        print(f'✗ {type(e).__name__}: {str(e)[:150]}')

asyncio.run(test())
