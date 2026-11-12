"""Parse per-video keyword tags with channel-default fallback."""
import re

def upload_tags(video_info, channel_config, log=print):
    raw=video_info.get('tags')
    if not raw or (isinstance(raw,str) and not raw.strip()):
        raw=channel_config.get('default_tags') or ['shorts','tiktok']
    values=re.split(r'[,;\r\n]+',raw) if isinstance(raw,str) else list(raw)
    result=[];seen=set();used=0;omitted=0
    for value in values:
        tag=' '.join(str(value).split()).strip()
        if not tag or tag.casefold() in seen:continue
        # YouTube counts commas and implicit quotation marks around multiword tags.
        cost=len(tag)+(2 if ' ' in tag else 0)+(1 if result else 0)
        if used+cost>500:
            omitted+=1;continue
        result.append(tag);seen.add(tag.casefold());used+=cost
    if omitted:log(f'Tags: omitted {omitted} entries to keep the YouTube 500-character budget')
    return result
