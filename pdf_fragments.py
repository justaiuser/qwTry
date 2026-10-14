"""Bounded page crops for dense, scanned reconciliation tables."""
from PIL import Image, ImageFilter


def fragment_page(page, side='Левая', split_percent=56, max_height=650):
    if side not in ('Левая', 'Правая', 'Вся страница'):
        raise ValueError('Некорректная сторона таблицы.')
    if not 20 <= split_percent <= 80:
        raise ValueError('Граница сторон должна быть от 20 до 80%.')
    import fitz
    pix = page.get_pixmap(matrix=fitz.Matrix(3,3), colorspace=fitz.csRGB)
    image=Image.frombytes('RGB',[pix.width,pix.height],pix.samples)
    width,height=image.size
    x0=0 if side!='Правая' else round(width*split_percent/100)
    x1=width if side!='Левая' else round(width*split_percent/100)
    image=image.crop((x0,0,x1,height))
    # Bound each input's visual token budget while retaining readable enlarged text.
    if image.width > 1100:
        image=image.resize((1100,round(image.height*1100/image.width)))
    gray=image.convert('L').filter(ImageFilter.MinFilter(9))
    width,height=image.size
    # Locate table borders to avoid cutting through multiline operation rows.
    groups=[]
    for y in range(height):
        dark=sum(gray.getpixel((x,y)) < 160 for x in range(0,width,3))
        if dark >= (width//3)*0.80:
            if not groups or y>groups[-1][-1]+2: groups.append([y])
            else: groups[-1].append(y)
    borders=[(g[0]+g[-1])//2 for g in groups]
    start=0; fragments=[]
    while start < height:
        target=min(start+max_height,height)
        near=[y for y in borders if target-140 <= y <= target and y>start+200]
        end=near[-1] if target<height and near else target
        overlap=0 if near and target<height else (70 if target<height else 0)
        # Overlap fallback handles skewed scans where borders cannot be detected.
        fragments.append((image.crop((0,start,width,min(height,end+overlap))),bool(overlap)))
        start=end
    return fragments


def merge_boundary(rows, incoming, overlap):
    """Remove only exact suffix/prefix overlap; preserve repeated rows elsewhere."""
    if overlap:
        for count in range(min(6,len(rows),len(incoming)),0,-1):
            if rows[-count:] == incoming[:count]:
                return rows+incoming[count:],count
    return rows+incoming,0
