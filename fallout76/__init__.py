from .fallout76 import Fallout76


async def setup(bot):
    await bot.add_cog(Fallout76(bot))
