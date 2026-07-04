import asyncio
import asyncpg
import os
from dotenv import load_dotenv

# Load .env explicitly
load_dotenv()

async def test():
    url_pooler = os.environ.get('SUPABASE_AVA_MEMORY_URL')
    if not url_pooler:
        print('ERROR: SUPABASE_AVA_MEMORY_URL not in environment')
        return
    
    # Try the standard (non-pooler) connection host
    url_standard = url_pooler.replace(
        'aws-1-eu-central-1.pooler.supabase.com:6543',
        'aws-1-eu-central-1.supabase.co:5432'
    )
    
    for name, url in [('Pooler', url_pooler), ('Standard', url_standard)]:
        print(f'[test] Trying {name} host...')
        print(f'  URL: {url}')
        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(url, statement_cache_size=0),
                timeout=5
            )
            
            row = await conn.fetchrow('SELECT current_user AS user, now() AS ts')
            print(f'  Success! Connected as: {row["user"]}')
            
            # List tables
            tables = await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name LIMIT 10"
            )
            table_names = [t['table_name'] for t in tables]
            print(f'  Tables: {", ".join(table_names)}')
            
            await conn.close()
            print()
            
        except Exception as e:
            print(f'  Failed: {type(e).__name__}: {str(e)[:120]}')
            print()

asyncio.run(test())
