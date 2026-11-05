$(document).ready(function() {
	
	var mobile = false;
	if( /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ) {
			mobile = true;
	}
	
	//функция для масштабирования на странице service/workshop
	(function(){
		var link = window.location.pathname;
		// console.log ('Новая функция');
		link = link.replace(/^\//g, '');
		link = link.replace(/\/$/g, '');
		// console.log (link);
		// console.log (link.search(/\/workshop/ig));
		if (link.search(/\/workshop/ig) != -1) {
			// console.log ('ресайзим воркшоп');
			resize();

			$('.scroll-pane').jScrollPane();
			if ($('.slider-cont ul').children().length <= 3) {
				$('.left_sc2').css({'display': 'none'});
				$('.right_sc2').css({'display': 'none'});
			}
			$('.left_sc2').click (function() {
				var amountSlide = $('.slider-cont ul').children().length;
				var widthSlide = $('.slider-cont ul').children().eq(0).outerWidth();
				var allSlideWidth = amountSlide*widthSlide;
				if (amountSlide > 3) {
					var positionX = $('.slider-cont ul').position().left;
					//positionX *= (-1);
					if (positionX != 0) {
						$('.slider-cont ul').animate({left: positionX+widthSlide}, 500);
					}
				}
				return false;
			});
			
			$('.right_sc2').click (function() {
				var amountSlide = $('.slider-cont ul').children().length;
				var widthSlide = $('.slider-cont ul').children().eq(0).outerWidth();
				var allSlideWidth = amountSlide*widthSlide;
				if (amountSlide > 3) {
					var positionX = $('.slider-cont ul').position().left;
					var amountHideSlides = (allSlideWidth-(-positionX+(3*widthSlide))) / widthSlide;
					// console.log (amountHideSlides);
					if (amountHideSlides > 0) {
						$('.slider-cont ul').animate({left: positionX-widthSlide}, 500);
					}
				}
				return false;
			});
		}
	})();
	
	(function () {
		var link = window.location.href;
		// console.log (link[link.length-1]);
		if (link[link.length-1] != '/') {
			link += '/';
			//console.log(link);
		}
		link += 'feed/'
		$( "#mini-search" ).autocomplete({
			source: link,
			close: function( event, ui ) {
				var Val = $("#mini-search").val();
				/**
				 * Делаем запрос на сервер для получения id
				 */
				$.ajax({
					url: link,
					dataType: 'json',
					type: 'POST',
					data: 'final='+Val,
					success: function (data) {
						var loc = window.location.href;
						/**
						 * Проверим, стоит ли последним символом символ "/"
						 */
						// console.log (loc[loc.length-1]);
						if (loc[loc.length-1] != '/') {
							loc += '/';
							// console.log(loc);
						}
						if (!data.error && (data.type!=undefined)) {
							loc = loc+data.type+'/';
							window.location.assign (loc);
						}
					}
				});
			}
			
		});
	})();

    /** Инициализация svg **/
    $('img.svg').each(function(){
        var $img = jQuery(this);
        var imgID = $img.attr('id');
        var imgClass = $img.attr('class');
        var imgURL = $img.attr('src');

        $.get(imgURL, function(data) {
            var $svg = jQuery(data).find('svg');
            if(typeof imgID !== 'undefined') $svg = $svg.attr('id', imgID);
            if(typeof imgClass !== 'undefined') $svg = $svg.attr('class', imgClass);
            $svg = $svg.removeAttr('xmlns:a');
            $img.replaceWith($svg);
        }, 'xml');
    });
	
	//Показать еще
	$('a.next-page.ajax-load').on('click', function() {
		var after = $(this).data('after');
		
		$(this).css('opacity', '0');
		//$('#load').show();
		
		if (after.length) {
			var a = this;
			var url = $(this).attr('href');
			var className = $(this).attr('class').replace(' ', '.');
			
			$.ajax({
				  type: "POST",
				  url: url,
				  dataType: 'html',
				  success: function(html){
					  html = $(html);
					  $(a).css('opacity', '1');
					  $(after, html).insertAfter(after + ':last');
					  var nl = $('a.'+className, html);
					  if (nl.length) {
						  $(a).attr('href', nl.attr('href'));
					  } else {
						  $('#paginator-padding').remove();
						  $(a).remove();
					  }
					  $('#load').hide();
				  }
			});
			return false;
		}
	});
	
	//filter
	$('.filter-news > a').click(function(event){
		event.preventDefault();
		$('.year').fadeIn();
		$('.month').hide();
	});
	
	$('.year > a').click(function(event){
		event.preventDefault();
		$('.year').hide();
		var text = $(this).html();
		var request = $.ajax({
			url: "/news/feed_filter/",
			type: "POST",
			data: { year : text },
			dataType: "html"
		});
		request.done(function( msg ) {
			$('.month #year').html(text);
			$('.month #month').html(msg);
			$('.month').fadeIn();
		});
	});

	$('.month-picker > .main > a').on('click', function(e){
		e.preventDefault();
		if($('.month-picker .months').html().trim()) {
			$('.month-picker .months').fadeToggle();
		}
		return false;
	});

	$('.month-picker .months a').on('click', function(e) {
		//e.preventDefault();
		$('.month-picker .months').fadeToggle();
		$('.month-picker .main > a').html($(this).html());
		//return false;
	});

	$('.month-picker .year a').on('click', function(e) {
		e.preventDefault();
		$('.month-picker .year').fadeOut();
		$('.month-picker .years').fadeIn();
		return false;
	});

	$('.month-picker .years a').on('click', function(e) {
		e.preventDefault();
		$('.month-picker .months').fadeOut();
		$('.month-picker .year a').html($(this).html());
		$('.month-picker .years').hide();
		$('.month-picker .year').fadeIn();

		var text = $(this).html();
		var request = $.ajax({
			url: "/workplan/feed_filter/",
			type: "POST",
			data: { year : text },
			dataType: "html"
		});
		request.done(function( msg ) {
			$('.month-picker .months').fadeOut(function () {
				$(this).html(msg);
			});
			if(msg) {
				$('.month-picker .months').fadeIn();
			}

		});
		return false;
	});

	$('html').on('click', function(){
		$('.month-picker .months').fadeOut();
		$('.month-picker .years').fadeOut();
		$('.month-picker .year').fadeIn();
	});
	
	//fancybox
	$(".fancybox").fancybox({
		openEffect	: 'fade',
		closeEffect	: 'fade',
		closeBtn      : false,
		beforeShow: function(){
			if(!mobile)
			$('.head-menu, .production, .news-content, .nav-part, .page-service-list, .service-list, h1, .background-service').css({
				"filter": "url('#blur')",
				"-webkit-filter": "blur(2px)"
				});
		},
		afterClose: function(){
			if(!mobile)
			$('.head-menu, .production, .news-content, .nav-part, .page-service-list, .service-list, h1, .background-service').css({
				"filter": "none",
				"-webkit-filter": "none"
				});
		}
	});
	
	$('.gallery').fancybox({
		openEffect	: 'fade',
		closeEffect	: 'fade',
		closeBtn      : false,
		arrows: true,
		beforeShow: function(){
			if(!mobile)
			$('.head-menu, .production, .news-content, .nav-part, .page-service-list, .service-list, h1, .background-service').css({
				"filter": "url('#blur')",
				"-webkit-filter": "blur(2px)"
				});
		},
		afterClose: function(){
			if(!mobile)
			$('.head-menu, .production, .news-content, .nav-part, .page-service-list, .service-list, h1, .background-service').css({
				"filter": "none",
				"-webkit-filter": "none"
				});	
			$(window.last).trigger('click');
		}
	});
	
	//slider
	$('#news-photo').lbSlider({
		leftBtn: '.sa-left-n',
		rightBtn: '.sa-right-n',
		visible: 3,
		autoPlay: false
	});
	
	$('.slider-cont1').lbSlider({
		leftBtn: '.left_sc1',
		rightBtn: '.right_sc1',
		visible: 3,
		autoPlay: false
	});
	$('.slider-cont2').lbSlider({
		leftBtn: '.left_sc2',
		rightBtn: '.right_sc2',
		visible: 3,
		autoPlay: false
	});
	$('.slider-cont3').lbSlider({
		leftBtn: '.left_sc3',
		rightBtn: '.right_sc3',
		visible: 3,
		autoPlay: false
	});
	$('.slider-cont4').lbSlider({
		leftBtn: '.left_sc4',
		rightBtn: '.right_sc4',
		visible: 3,
		autoPlay: false
	});
	$('.slider-cont10').lbSlider({
		leftBtn: '.left_sc10',
		rightBtn: '.right_sc10',
		visible: 3,
		autoPlay: false
	});
	
	$('#service-photo').lbSlider({
		leftBtn: '.sa-left-n',
		rightBtn: '.sa-right-n',
		visible: 4,
		autoPlay: false
	});
	
	$('#menu-properties').lbSlider({
		leftBtn: '.sa-left',
		rightBtn: '.sa-right',
		visible: 4,
		autoPlay: false
	});
	
	var subItem = $('#sub-menu-properties a').length;
	
	if(subItem > 16){
		$('#sub-menu-properties').lbSlider({
			leftBtn: '.sa-left-s',
			rightBtn: '.sa-right-s',
			visible: 4,
			autoPlay: false
		});
	}else{
		$('.sa-left-s, .sa-right-s').remove();
	}
	
	//modal
	$("a.modal-link").fancybox({
		openEffect	: 'fade',
		closeEffect	: 'fade',
		closeBtn      : false,
		beforeLoad: function (){
			window.last = this.element;
		},
		beforeShow: function(){
			if(!mobile)
			$('.head-menu, .nav-part, .page-service-list, .service-list, h1, .background-service').css({
				"filter": "url('#blur')",
				"-webkit-filter": "blur(2px)"
				});
		},
		afterClose: function(){
			if(!mobile)
			$('.head-menu, .nav-part, .page-service-list, .service-list, h1, .background-service').css({
				"filter": "none",
				"-webkit-filter": "none"
				});
		}
	});
	
	/**
	 * Работа с пагинатором и публикация пришедших значений
	 */
	$('#moreOffer').click( function () {
		var link = $(this).attr ('data-position');
		$.ajax({
			url: link,
			dataType: 'json',
			type: 'POST',
			data: 'pageAjax=1',
			success: function (data) {
				/**
				 * После получения ответа навешиваем событие для 
				 * появления всплывающего окна
				 */
				var more = data.more;
				var data = $(data.answer);
				data.find('a.modal-link').fancybox({
					openEffect	: 'fade',
					closeEffect	: 'fade',
					closeBtn      : false,
					beforeShow: function(){
						if(!mobile)
						$('.head-menu, .nav-part, .page-service-list, .service-list, h1, .background-service').css({
							"filter": "url('#blur')",
							"-webkit-filter": "blur(2px)"
							});
					},
					afterClose: function(){
						if(!mobile)
						$('.head-menu, .nav-part, .page-service-list, .service-list, h1, .background-service').css({
							"filter": "none",
							"-webkit-filter": "none"
							});
					}
				});
				$('div.list-properties > ul').append (data);
				// console.log('Ссылка на следующую страницу: '+more);
				if (more) {
					$('#moreOffer').attr('data-position', more);
				} else {
					$('#moreOffer').css ({'display':'none'});
				}
				resize();
				centering(data.find('samp'));
			}
		});
		return false;
	});
	
	//order
	
	$('#phone').bind("change keyup input click", function() {
		if (this.value.match(/[^0-9]/g)) {
			this.value = this.value.replace(/[^0-9]/g, '');
    	}
	});
	
	$('label[for=people]').click(function(){
		$('#input_name_org').css('opacity', '0');
	});
	
	$('label[for=organization]').click(function(){
		$('#input_name_org').css('opacity', '1');
		$('#name_org').val('');
	});
	
	var post = false;
	$( "form.order" ).submit(function( event ) {

		if(!post) {
			event.preventDefault();
		}
		
		var error = false;
		var error_email = false;
		
		if($('#name').val() == '') {
			$('#name').css('border-color', '#cd983b');
			$('label[for=name]').css('color', '#cd983b');
			error = true;
		}else{
			$('#name').css('border-color', '#cacaca');
			$('label[for=name]').css('color', '#606060');
		}
		
		if($('#info').val() == '') {
			$('#info').css('border-color', '#cd983b');
			$('label[for=info]').css('color', '#cd983b');
			error = true;
		}else{
			$('#info').css('border-color', '#cacaca');
			$('label[for=info]').css('color', '#606060');
		}

		if($('#organization').is(':checked')){
			if($('#name_org').val() == '') {
				$('#name_org').css('border-color', '#cd983b');
				$('label[for=name_org]').css('color', '#cd983b');
				error = true;
			}else{
				$('#name_org').css('border-color', '#cacaca');
				$('label[for=name_org]').css('color', '#606060');
			}
		}
		
		if($('#phone').val() == '') {
			$('#phone').css('border-color', '#cd983b');
			$('label[for=phone]').css('color', '#cd983b');
			error = true;
		}else{
			$('#phone').css('border-color', '#cacaca');
			$('label[for=phone]').css('color', '#606060');
		}
		
		if($('#info').val() == '') {
			$('#info').css('border-color', '#cd983b');
			$('label[for=info]').css('color', '#cd983b');
			error = true;
		}else{
			$('#info').css('border-color', '#cacaca');
			$('label[for=info]').css('color', '#606060');
		}
		
		if($('#email').val() != '') {
            var pattern = /^([a-z0-9_\.-])+@[a-z0-9-]+\.([a-z]{2,4}\.)?[a-z]{2,4}$/i;
            if(pattern.test($('#email').val())){
            	$('#email').css('border-color', '#cacaca');
    			$('label[for=email]').css('color', '#606060');
            }else{
            	$('#email').css('border-color', '#cd983b');
    			$('label[for=email]').css('color', '#cd983b');
    			error_email = true;
            }
        } else {
        	$('#email').css('border-color', '#cd983b');
			$('label[for=email]').css('color', '#cd983b');
			error = true;
        }
		
		if(!error && !error_email) {
			$('#message').html('Мы проверили форму, она заполнена верно!<br>Подтвердите отправку формы в течении 30 секунд.');
			
			post = true;
			var i = 30;
			var interval = setInterval(function() {
				$("input[type=submit]").val('Отправить ('+i+')');
				if(i == -1) {
					post = false;
					clearInterval(interval);
					$("input[type=submit]").val('Отправить');
					$('#message').html('<font color="#cd983b">Время истекло!<br>Повторыте отправку.</font>');
				}
				i--;
			}, 1000);

		} else if(error_email) {
			$('#message').html('<font color="#cd983b">Email не корректен!</font>');
		} else {
			$('#message').html('<font color="#cd983b">Заполнены не все поля!</font>');
		}
				
		$('#message').show();
		
	});
	
	//поиск по реквизиту
	$('.properties .search input').bind("change keyup input click", function(){
		if($(this).val() != ''){
			$('button', $(this).parent()).show();
		}else{
			$('button', $(this).parent()).hide();
		}
	})
	
	//переключение табов
	$('.nav-tabs li a').click(function(event){
		event.preventDefault();
		if($(this).attr('href') != '#'){
			var parent = $(this).parents('.content');
			$('.nav-tabs li', parent).removeClass('active');
			$(this).parent().addClass('active');
			$('.tabs', parent).hide();
			$($(this).attr('href'), parent).show();
			resize();
		}
	});

    //Переключение по клику на дате
    $('.start-year, .stop-year').click(function(event){
        event.preventDefault();
        if($(this).attr('href') != '#'){
            var parent = $(this).parents('.content');
            $('.nav-tabs li', parent).removeClass('active');
            $('a[href='+$(this).attr('href')+']').parent().addClass('active');
            $('.tabs', parent).hide();
            $($(this).attr('href'), parent).show();
        }
    })

	$(window).resize(function() {
	 	resize();
	 	centering($('.list-properties li samp, .propsImg samp'));
    });
	//resize();
	
	/**
	 * Центрируем все артикулы
	 */
	centering($('.list-properties li samp, .propsImg samp'));
	
	/**
	 * Работаем только с полем формы заказа реквизита с полем
	 * ввода количества
	 */
	$('#amount').bind("change keyup input click", function() {
	    if (this.value.match(/[^0-9]/g)) {
	        this.value = this.value.replace(/[^0-9]/g, '');
	    }
	});



    $('.main-service > ul > li').each(function(i, item){
        var parent = $(item);
        var more = false;
        var num = 0;
        $('li', parent).each(function(i, item){
            var height = $(item).height();
            var pos = $(item).position().top + 15;
            if(pos > 190) {
                if(!more) more = $(item);
                $(item).addClass('hide');
                num++;
            }
        });
        if(more) more.before('<li class="more"><p><a href="#">еще '+num+'</a></p></li>');
    });

    var map;
    function initialize() {
        var mapOptions = {
            mapTypeControl: false,
            streetViewControl: false,
            zoom: 14,
            scrollwheel: false,
            center: {lat: 59.958006, lng: 30.317012}
        };
        var map = new google.maps.Map(document.getElementById('mainMap'), mapOptions);
        var marker = new google.maps.Marker({
            position: {lat: 59.958006, lng: 30.317012},
            map: map,
            icon: {
                url: '/site/css/img/marker.png',
                scaledSize : new google.maps.Size(46, 47)
            }
        });
        var styles = [{"featureType":"water","elementType":"geometry.fill","stylers":[{"color":"#d3d3d3"}]},{"featureType":"transit","stylers":[{"color":"#808080"},{"visibility":"off"}]},{"featureType":"road.highway","elementType":"geometry.stroke","stylers":[{"visibility":"on"},{"color":"#b3b3b3"}]},{"featureType":"road.highway","elementType":"geometry.fill","stylers":[{"color":"#ffffff"}]},{"featureType":"road.local","elementType":"geometry.fill","stylers":[{"visibility":"on"},{"color":"#ffffff"},{"weight":1.8}]},{"featureType":"road.local","elementType":"geometry.stroke","stylers":[{"color":"#d7d7d7"}]},{"featureType":"poi","elementType":"geometry.fill","stylers":[{"visibility":"on"},{"color":"#ebebeb"}]},{"featureType":"administrative","elementType":"geometry","stylers":[{"color":"#a7a7a7"}]},{"featureType":"road.arterial","elementType":"geometry.fill","stylers":[{"color":"#ffffff"}]},{"featureType":"road.arterial","elementType":"geometry.fill","stylers":[{"color":"#ffffff"}]},{"featureType":"landscape","elementType":"geometry.fill","stylers":[{"visibility":"on"},{"color":"#efefef"}]},{"featureType":"road","elementType":"labels.text.fill","stylers":[{"color":"#696969"}]},{"featureType":"administrative","elementType":"labels.text.fill","stylers":[{"visibility":"on"},{"color":"#737373"}]},{"featureType":"poi","elementType":"labels.icon","stylers":[{"visibility":"off"}]},{"featureType":"poi","elementType":"labels","stylers":[{"visibility":"off"}]},{"featureType":"road.arterial","elementType":"geometry.stroke","stylers":[{"color":"#d6d6d6"}]},{"featureType":"road","elementType":"labels.icon","stylers":[{"visibility":"off"}]},{},{"featureType":"poi","elementType":"geometry.fill","stylers":[{"color":"#dadada"}]}];
        map.setOptions({styles: styles});
    }
    if($('#mainMap').length > 0) {
		//google.maps.event.addDomListener(window, 'load', initialize);
	}

});

function resize(){
	$('body').css('height', '');
	var height = $(document).height();
	var content_height = $('#size').height();
	if(content_height < height && content_height)
		$('body').height(height);
}

function centering(arrayOfElems){
	var item = 0;
	var selfWidth = 0;
	var parentWidth = 0;
	var freeSpace = 0;
	for (var i = 0, length = arrayOfElems.length; i<length; i+=1) {
		item = arrayOfElems.eq(i);
		selfWidth = item.width();
		parentWidth = item.parent().parent().width();
		freeSpace = parentWidth-selfWidth;
		freeSpace = freeSpace/2;
		item.css({'left':freeSpace+'px'});
	}
}

//Кнопка прокрутки вверх
$(function() {
    $('.arrow-up-site').click(function() {
        $('html, body').animate({scrollTop: 0}, 800)
    });
    $(window).scroll(function() {
        if($(this).scrollTop() > 500) {$('.arrow-up-site').removeClass('hide')}
        else {$('.arrow-up-site').addClass('hide')}
    });
})
