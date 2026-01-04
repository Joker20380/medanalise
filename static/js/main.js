AOS.init({
  duration: 800,
  easing: 'slide'
});

(function ($) {

  "use strict";

  /* ===============================
     Stellar (parallax)
  =============================== */
  $(window).stellar({
    responsive: true,
    parallaxBackgrounds: true,
    parallaxElements: true,
    horizontalScrolling: false,
    hideDistantElements: false,
    scrollProperty: 'scroll'
  });

  /* ===============================
     Full height
  =============================== */
  var fullHeight = function () {
    $('.js-fullheight').css('height', $(window).height());
    $(window).resize(function () {
      $('.js-fullheight').css('height', $(window).height());
    });
  };
  fullHeight();

  /* ===============================
     Loader
  =============================== */
  var loader = function () {
    setTimeout(function () {
      if ($('#ftco-loader').length > 0) {
        $('#ftco-loader').removeClass('show');
      }
    }, 1);
  };
  loader();

  /* ===============================
     Scrollax
  =============================== */
  $.Scrollax();

  /* ===============================
     Burger menu
  =============================== */
  var burgerMenu = function () {
    $('body').on('click', '.js-fh5co-nav-toggle', function (event) {
      event.preventDefault();
      $(this).toggleClass('active');
    });
  };
  burgerMenu();

  /* ===============================
     One page scroll
  =============================== */
  var onePageClick = function () {
    $(document).on('click', '#ftco-nav a[href^="#"]', function (event) {
      event.preventDefault();
      var href = $.attr(this, 'href');
      $('html, body').animate({
        scrollTop: $(href).offset().top - 70
      }, 500);
    });
  };
  onePageClick();

  /* ===============================
     Owl Carousels
  =============================== */
  var carousel = function () {

    /* Home slider */
    $('.home-slider').owlCarousel({
      loop: true,
      autoplay: true,
      margin: 0,
      animateOut: 'fadeOut',
      animateIn: 'fadeIn',
      nav: false,
      autoplayHoverPause: false,
      items: 1,
      navText: [
        "<span class='ion-md-arrow-back'></span>",
        "<span class='ion-chevron-right'></span>"
      ]
    });

    /* Properties carousel */
    $('.carousel-properties').owlCarousel({
      autoplay: true,
      center: false,
      loop: true,
      margin: 30,
      nav: false,
      responsive: {
        0: { items: 1 },
        600: { items: 2 },
        1000: { items: 3 }
      }
    });

    /* Agent carousel */
    $('.carousel-agent').owlCarousel({
      autoplay: true,
      center: false,
      loop: true,
      margin: 30,
      nav: false,
      responsive: {
        0: { items: 1 },
        600: { items: 2 },
        1000: { items: 3 }
      }
    });

    /* Testimony carousel */
    $('.carousel-testimony').owlCarousel({
      autoplay: true,
      autoHeight: true,
      center: true,
      loop: true,
      margin: 30,
      nav: false,
      dots: true,
      responsive: {
        0: { items: 1 },
        600: { items: 2 },
        1000: { items: 3 }
      }
    });

    /* ===============================
       NEWS carousel (твоя)
    =============================== */
    var $news = $('.news-carousel');
    if ($news.length && !$news.hasClass('owl-loaded')) {
      $news.owlCarousel({
        autoplay: true,
        loop: true,
        margin: 30,
        nav: true,
        dots: true,
        autoplayTimeout: 7000,
        autoplayHoverPause: true,
        smartSpeed: 700,
        navText: [
          '<span class="ion-ios-arrow-back"></span>',
          '<span class="ion-ios-arrow-forward"></span>'
        ],
        responsive: {
          0: { items: 1 },
          768: { items: 2 },
          992: { items: 3 }
        }
      });
    }
  };
  carousel();

  /* ===============================
     Dropdown hover
  =============================== */
  $('nav .dropdown').hover(
    function () {
      $(this).addClass('show');
      $(this).find('> a').attr('aria-expanded', true);
      $(this).find('.dropdown-menu').addClass('show');
    },
    function () {
      $(this).removeClass('show');
      $(this).find('> a').attr('aria-expanded', false);
      $(this).find('.dropdown-menu').removeClass('show');
    }
  );

  /* ===============================
     Scroll effects
  =============================== */
  var scrollWindow = function () {
    $(window).scroll(function () {
      var st = $(this).scrollTop(),
          navbar = $('.ftco_navbar'),
          sd = $('.js-scroll-wrap');

      if (st > 150) navbar.addClass('scrolled');
      if (st < 150) navbar.removeClass('scrolled sleep');
      if (st > 350) {
        navbar.addClass('awake');
        sd.addClass('sleep');
      }
      if (st < 350) {
        navbar.removeClass('awake').addClass('sleep');
        sd.removeClass('sleep');
      }
    });
  };
  scrollWindow();

  /* ===============================
     Counter
  =============================== */
  var counter = function () {
    $('#section-counter, .hero-wrap, .ftco-counter').waypoint(function (direction) {
      if (direction === 'down' && !$(this.element).hasClass('ftco-animated')) {
        $('.number').each(function () {
          var $this = $(this),
              num = $this.data('number');
          $this.animateNumber({ number: num }, 7000);
        });
      }
    }, { offset: '95%' });
  };
  counter();

  /* ===============================
     Content animations
  =============================== */
  var contentWayPoint = function () {
    $('.ftco-animate').waypoint(function (direction) {
      if (direction === 'down' && !$(this.element).hasClass('ftco-animated')) {
        $(this.element).addClass('fadeInUp ftco-animated');
      }
    }, { offset: '95%' });
  };
  contentWayPoint();

  /* ===============================
     Magnific Popup
  =============================== */
  $('.image-popup').magnificPopup({
    type: 'image',
    closeOnContentClick: true,
    fixedContentPos: true,
    gallery: { enabled: true }
  });

  $('.popup-youtube, .popup-vimeo, .popup-gmaps').magnificPopup({
    disableOn: 700,
    type: 'iframe',
    mainClass: 'mfp-fade',
    removalDelay: 160,
    preloader: false,
    fixedContentPos: false
  });

})(jQuery);
