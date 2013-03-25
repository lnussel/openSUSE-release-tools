#! /usr/bin/perl -w

BEGIN {
  unshift @INC, "/usr/lib/build/Build";
}

use File::Basename;
use File::Temp qw/ tempdir  /;
use XML::Simple;
use Data::Dumper;
use Cwd;
use Rpm;

use strict;

my $dir = $ARGV[0];
my %toignore;
foreach my $name (split(/,/, $ARGV[1])) {
   $toignore{$name} = 1;
}

if (! -f "$dir/rpmlint.log") {
  print "Couldn't find a rpmlint.log in the build results. This is mandatory\n";
  exit(1);
}

open(GREP, "grep 'W:.*invalid-lcense ' $dir/rpmlint.log |");
while ( <GREP> ) {
  print "Found rpmlint warning: ";
  print $_;
  exit(1);
}

my %targets;
my %cache;

foreach my $file (glob("~/cache/*")) {
  if ($file =~ m,/(\d+)\.(\d+)-([^/]*)$,) {
    $cache{"$1.$2"} = $3;
  }
}

sub write_package($$)
{
  my $ignore = shift;
  my $package = shift;

  # RPMTAG_FILEMODES            = 1030, /* h[] */
  # RPMTAG_FILEFLAGS            = 1037, /* i[] */
  # RPMTAG_FILEUSERNAME         = 1039, /* s[] */
  # RPMTAG_FILEGROUPNAME        = 1040, /* s[] */

  my ($dev,$ino,$mode,$nlink,$uid,$gid,$rdev,$size,
      $atime,$mtime,$ctime,$blksize,$blocks);

  # use cache
  if ($ignore == 1) {
    ($dev,$ino,$mode,$nlink,$uid,$gid,$rdev,$size,
      $atime,$mtime,$ctime,$blksize,$blocks) = stat($package);
    if ($cache{"$mtime.$ino"}) {
      my $name = $cache{"$mtime.$ino"};
      if (defined $toignore{$name}) {
	return;
      }
      open(C, $ENV{'HOME'} . "/cache/$mtime.$ino-$name") || die "no cache for $package";
      while ( <C> ) {
	print PACKAGES $_;
      }
      close(C);
      return;
    }
  }

  my %qq = Build::Rpm::rpmq("$package", qw{NAME VERSION RELEASE ARCH OLDFILENAMES DIRNAMES BASENAMES DIRINDEXES 1030 1037 1039 1040
					   1047 1112 1113 1049 1048 1050 1090 1114 1115 1054 1053 1055
					});

  my $name = $qq{'NAME'}[0];
  if ($ignore == 1 && defined $toignore{$name}) {
      return;
  }

  if ($ignore == 0) {
    $targets{$name} = 1;
  }

  Build::Rpm::add_flagsvers(\%qq, 1049, 1048, 1050); # requires
  Build::Rpm::add_flagsvers(\%qq, 1047, 1112, 1113); # provides
  Build::Rpm::add_flagsvers(\%qq, 1090, 1114, 1115); # obsoletes
  Build::Rpm::add_flagsvers(\%qq, 1054, 1053, 1055); # conflicts

  my $out = '';
  $out .= sprintf("=Pkg: %s %s %s %s\n", $name, $qq{'VERSION'}[0], $qq{'RELEASE'}[0], $qq{'ARCH'}[0]);
  $out .= "+Flx:\n";
  my @modes = @{$qq{1030} || []};
  my @basenames = @{$qq{BASENAMES} || []};
  my @dirs = @{$qq{DIRNAMES} || []};
  my @dirindexes = @{$qq{DIRINDEXES} || []};
  my @users = @{$qq{1039} || []};
  my @groups = @{$qq{1040} || []};
  my @flags = @{$qq{1037} || []};

  my @xprvs;

  foreach my $bname (@basenames) {
    my $mode = shift @modes;
    my $di = shift @dirindexes;
    my $user = shift @users;
    my $group = shift @groups;
    my $flag = shift @flags;

    my $filename = $dirs[$di] . $bname;
    $out .= sprintf "%o %o %s:%s %s\n", $mode, $flag, $user, $group, $filename;
    if ( $filename =~ /^\/etc\// || $filename =~ /bin\// || $filename eq "/usr/lib/sendmail" ) {
      push @xprvs, $filename;
    }
  }
  $out .= "-Flx:\n";
  $out .= "+Prv:\n";
  foreach my $prv (@{$qq{1047} || []}) {
    $out .= "$prv\n";
  }
  foreach my $prv (@xprvs) {
    $out .= "$prv\n";
  }
  $out .= "-Prv:\n";
  $out .= "+Con:\n";
  foreach my $prv (@{$qq{1054} || []}) {
    $out .= "$prv\n";
  }
  $out .= "-Con:\n";
  $out .= "+Req:\n";
  foreach my $prv (@{$qq{1049} || []}) {
    $out .= "$prv\n" unless $prv =~ m/^rpmlib/;
  }
  $out .= "-Req:\n";
  $out .= "+Obs:\n";
  foreach my $prv (@{$qq{1090} || []}) {
    $out .= "$prv\n";
  }
  $out .= "-Obs:\n";

  if ($ignore == 1) {
    open(C, '>', $ENV{'HOME'} . "/cache/$mtime.$ino-$name") || die "no writeable cache for $package";
    print C $out;
    close(C);
  }

  print PACKAGES $out;
}

my @rpms = glob("~/factory-repo/*.rpm");
my $pfile = $ENV{'HOME'} . "/packages";
open(PACKAGES, ">", $pfile) || die 'can not open';
print PACKAGES "=Ver: 2.0\n";

foreach my $package (@rpms) {
    write_package(1, $package);
}

@rpms = glob("$dir/*.rpm");
foreach my $package (@rpms) {
    write_package(0, $package);
}

close(PACKAGES);

#print "calling installcheck\n";
#print Dumper(%targets);
open(INSTALL, "~mls/bin/installcheck x86_64 $pfile 2>&1|") || die 'exec installcheck';
while ( <INSTALL> ) {
    chomp;
    next if (m/unknown line:.*Flx/);
    if ($_ =~ m/can't install (.*)-([^-]*)-[^-\.]/) {
#	print "CI $1\n";
        if (defined $targets{$1}) {
	  print "$_\n";
	  while ( <INSTALL> ) {
	    last if (m/^can't install /);
	    print "$_";
	  }
	  close(INSTALL);
          exit(1);
        }
    }
}
close(INSTALL);

#print "checking file conflicts\n";
open(INSTALL, "perl findfileconflicts $pfile 2>&1|") || die 'exec fileconflicts';
while ( <INSTALL> ) {
    chomp;
    #print STDERR "$_\n";
    if ($_ =~ m/found conflict of (\S+) .* with (\S+) /) {
        if (defined $targets{$1} || defined $targets{$2}) {
          print "FC $1 $2\n";
          exit(1);
        }
    }
}
close(INSTALL);

exit(0);
