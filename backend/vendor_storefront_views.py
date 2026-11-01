import json

from django.http import JsonResponse
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny

from backend.models import Category, PageItem, PageItemOption, ProductOption, Slide
from backend.vendor_auth_views import _vendor_from_request

VIEW_LABELS = {1: 'Banner', 2: 'Swiper', 3: 'Grid', 4: 'Row', 5: 'Offers'}


def _vendor_or_error(request):
    vendor = _vendor_from_request(request)
    if vendor is None:
        return None, JsonResponse({'error': 'Sign in again.'}, status=401)
    return vendor, None


def _image_url(request, image):
    if not image:
        return ''
    try:
        return request.build_absolute_uri(image.url)
    except Exception:
        return ''


def _slide_payload(request, slide):
    return {
        'id': slide.id,
        'position': slide.position,
        'category': slide.category_id,
        'category_name': slide.category.name,
        'image': _image_url(request, slide.image),
    }


def _ordered_links(item):
    return item.option_links.select_related('product_option__product').order_by('position', 'id')


def _assign_options(item, options):
    keep = [option.id for option in options]
    item.option_links.exclude(product_option_id__in=keep).delete()
    for index, option in enumerate(options):
        PageItemOption.objects.update_or_create(
            page_item=item,
            product_option=option,
            defaults={'position': index},
        )


def _page_item_payload(request, item):
    options = []
    for link in _ordered_links(item)[:40]:
        options.append({
            'id': str(link.product_option_id),
            'title': str(link.product_option),
        })
    return {
        'id': item.id,
        'position': item.position,
        'title': item.title,
        'viewtype': item.viewtype,
        'viewtype_label': VIEW_LABELS.get(item.viewtype, 'Section'),
        'category': item.category_id,
        'category_name': item.category.name,
        'image': _image_url(request, item.image),
        'product_options': options,
    }


def _category(raw):
    try:
        return Category.objects.get(id=int(raw))
    except (TypeError, ValueError, Category.DoesNotExist):
        return None


def _position(raw, default=0):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _option_ids(data):
    raw = data.get('product_option_ids')
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except ValueError:
            raw = [part.strip() for part in text.split(',') if part.strip()]
    if not isinstance(raw, list):
        raise ValueError('Choose products from your shop.')
    return [str(item) for item in raw if str(item).strip()]


def _owned_options(vendor, option_ids):
    wanted = list(dict.fromkeys(option_ids))
    found = {
        str(option.id): option
        for option in ProductOption.objects.filter(id__in=wanted, product__vendor=vendor)
    }
    if len(found) != len(wanted):
        return None
    return [found[item] for item in wanted]


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_storefront(request):
    vendor, error = _vendor_or_error(request)
    if error is not None:
        return error
    slides = Slide.objects.filter(vendor=vendor).select_related('category').order_by('position', 'id')
    items = PageItem.objects.filter(vendor=vendor).select_related('category').order_by('position', 'id')
    return JsonResponse({
        'slides': [_slide_payload(request, slide) for slide in slides],
        'page_items': [_page_item_payload(request, item) for item in items],
    })


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_slide_create(request):
    vendor, error = _vendor_or_error(request)
    if error is not None:
        return error
    category = _category(request.data.get('category'))
    image = request.FILES.get('image')
    if category is None:
        return JsonResponse({'error': 'Choose a category.'}, status=400)
    if image is None:
        return JsonResponse({'error': 'Add a banner image.'}, status=400)
    slide = Slide.objects.create(
        vendor=vendor,
        category=category,
        position=_position(request.data.get('position')),
        image=image,
    )
    return JsonResponse(_slide_payload(request, slide), status=201)


@api_view(['POST', 'DELETE'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_slide_detail(request, slide_id):
    vendor, error = _vendor_or_error(request)
    if error is not None:
        return error
    slide = Slide.objects.filter(id=slide_id, vendor=vendor).select_related('category').first()
    if slide is None:
        return JsonResponse({'error': 'Banner not found.'}, status=404)
    if request.method == 'DELETE':
        if slide.image:
            slide.image.delete(save=False)
        slide.delete()
        return JsonResponse({'ok': True})
    category = _category(request.data.get('category')) or slide.category
    slide.category = category
    if 'position' in request.data:
        slide.position = _position(request.data.get('position'), slide.position)
    image = request.FILES.get('image')
    if image is not None:
        if slide.image:
            slide.image.delete(save=False)
        slide.image = image
    slide.save()
    return JsonResponse(_slide_payload(request, slide))


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_page_item_create(request):
    vendor, error = _vendor_or_error(request)
    if error is not None:
        return error
    category = _category(request.data.get('category'))
    if category is None:
        return JsonResponse({'error': 'Choose a category.'}, status=400)
    try:
        viewtype = int(request.data.get('viewtype') or 1)
    except (TypeError, ValueError):
        viewtype = 0
    if viewtype not in VIEW_LABELS:
        return JsonResponse({'error': 'Choose banner, swiper, grid, row, or offers.'}, status=400)
    try:
        option_ids = _option_ids(request.data) or []
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    options = _owned_options(vendor, option_ids)
    if options is None:
        return JsonResponse({'error': 'Choose products from your shop.'}, status=400)
    item = PageItem(
        vendor=vendor,
        category=category,
        position=_position(request.data.get('position')),
        title=str(request.data.get('title') or '')[:50],
        viewtype=viewtype,
    )
    image = request.FILES.get('image')
    if image is not None:
        item.image = image
    item.save()
    _assign_options(item, options)
    return JsonResponse(_page_item_payload(request, item), status=201)


@api_view(['POST', 'DELETE'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_page_item_detail(request, item_id):
    vendor, error = _vendor_or_error(request)
    if error is not None:
        return error
    item = PageItem.objects.filter(id=item_id, vendor=vendor).select_related('category').first()
    if item is None:
        return JsonResponse({'error': 'Section not found.'}, status=404)
    if request.method == 'DELETE':
        if item.image:
            item.image.delete(save=False)
        item.delete()
        return JsonResponse({'ok': True})
    category = _category(request.data.get('category'))
    if category is not None:
        item.category = category
    if 'position' in request.data:
        item.position = _position(request.data.get('position'), item.position)
    if 'title' in request.data:
        item.title = str(request.data.get('title') or '')[:50]
    if 'viewtype' in request.data:
        try:
            viewtype = int(request.data.get('viewtype'))
        except (TypeError, ValueError):
            viewtype = 0
        if viewtype not in VIEW_LABELS:
            return JsonResponse({'error': 'Choose banner, swiper, grid, row, or offers.'}, status=400)
        item.viewtype = viewtype
    image = request.FILES.get('image')
    if image is not None:
        if item.image:
            item.image.delete(save=False)
        item.image = image
    try:
        option_ids = _option_ids(request.data)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    item.save()
    if option_ids is not None:
        options = _owned_options(vendor, option_ids)
        if options is None:
            return JsonResponse({'error': 'Choose products from your shop.'}, status=400)
        _assign_options(item, options)
    return JsonResponse(_page_item_payload(request, item))
